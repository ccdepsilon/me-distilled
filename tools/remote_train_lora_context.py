import argparse
import json
import math
import os
import random
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from torch.utils.data import DataLoader, Dataset
from tqdm.auto import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup


SYSTEM_PROMPT = (
    "你是一个中文微信聊天模型，模仿“我”的聊天方式和语气。你正在和朋友微信聊天。"
    "请参考前面的上下文，但只回复最后一条用户消息。如果提供了相关记忆，可以参考这些信息，但不要生硬复述。"
    "回复要自然、简短，像朋友微信聊天。不要像 AI 助手，不要讲大道理，不要主动总结，不要列举建议，"
    "不要替用户继续说话，不要续写完整聊天记录。可以一条或多条短句回复；如果多条短句，用换行分开。"
)


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class ChatDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.items: list[dict[str, torch.Tensor]] = []
        skipped_no_labels = 0
        for row in rows:
            item = self.encode_row(row)
            if item is None:
                skipped_no_labels += 1
                continue
            self.items.append(item)
        if skipped_no_labels:
            print(f"filtered_rows_without_supervised_tokens: {skipped_no_labels}")

    def __len__(self) -> int:
        return len(self.items)

    def encode_row(self, row: dict) -> dict[str, torch.Tensor] | None:
        messages = row["messages"]
        prompt_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[
                {
                    "role": message["role"],
                    "content": str(message.get("content") or "").strip(),
                }
                for message in messages[:-1]
            ],
        ]
        assistant = str(messages[-1].get("content") or "").strip()

        prompt = self.tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        full = prompt + assistant + self.tokenizer.eos_token

        prompt_ids = self.tokenizer(prompt, add_special_tokens=False)["input_ids"]
        enc = self.tokenizer(
            full,
            add_special_tokens=False,
            truncation=True,
            max_length=self.max_length,
        )
        input_ids = enc["input_ids"]
        labels = input_ids.copy()
        cutoff = min(len(prompt_ids), len(labels))
        labels[:cutoff] = [-100] * cutoff
        if all(label == -100 for label in labels):
            return None
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    def __getitem__(self, idx: int) -> dict:
        return self.items[idx]


class Collator:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def __call__(self, features: list[dict]) -> dict:
        max_len = max(len(f["input_ids"]) for f in features)
        pad_id = self.tokenizer.pad_token_id
        input_ids = []
        labels = []
        attention_mask = []
        for f in features:
            length = len(f["input_ids"])
            pad = max_len - length
            input_ids.append(torch.cat([f["input_ids"], torch.full((pad,), pad_id, dtype=torch.long)]))
            labels.append(torch.cat([f["labels"], torch.full((pad,), -100, dtype=torch.long)]))
            attention_mask.append(torch.cat([torch.ones(length, dtype=torch.long), torch.zeros(pad, dtype=torch.long)]))
        return {
            "input_ids": torch.stack(input_ids),
            "labels": torch.stack(labels),
            "attention_mask": torch.stack(attention_mask),
        }


def split_rows(rows: list[dict], seed: int, eval_size: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    rows = rows.copy()
    rng.shuffle(rows)
    eval_size = min(eval_size, max(1, len(rows) // 20))
    return rows[eval_size:], rows[:eval_size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--max_length", type=int, default=256)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--grad_accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=8e-5)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval_size", type=int, default=120)
    parser.add_argument("--save_steps", type=int, default=120)
    parser.add_argument("--resume_adapter", default="")
    parser.add_argument("--resume_global_step", type=int, default=0)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, trust_remote_code=True, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    rows = read_jsonl(Path(args.data))
    train_rows, eval_rows = split_rows(rows, args.seed, args.eval_size)

    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable()

    if args.resume_adapter:
        model = PeftModel.from_pretrained(model, args.resume_adapter, is_trainable=True)
    else:
        lora = LoraConfig(
            r=args.rank,
            lora_alpha=args.alpha,
            lora_dropout=args.dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        )
        model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_ds = ChatDataset(train_rows, tokenizer, args.max_length)
    eval_ds = ChatDataset(eval_rows, tokenizer, args.max_length)
    collator = Collator(tokenizer)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collator)
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collator)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    total_steps = math.ceil(len(train_loader) * args.epochs / args.grad_accum)
    warmup_steps = max(10, total_steps // 20)
    scheduler = get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps)
    scaler = torch.amp.GradScaler("cuda")

    global_step = args.resume_global_step
    accum_loss = 0.0
    model.train()
    num_epochs = math.ceil(args.epochs)
    max_batches = int(len(train_loader) * args.epochs)
    pbar = tqdm(total=max_batches, desc="train")
    seen_batches = 0

    for _epoch in range(num_epochs):
        for batch in train_loader:
            if seen_batches >= max_batches:
                break
            if global_step >= total_steps:
                break
            seen_batches += 1
            batch = {k: v.to(model.device) for k, v in batch.items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                loss = model(**batch).loss / args.grad_accum
            scaler.scale(loss).backward()
            accum_loss += loss.item()

            if seen_batches % args.grad_accum == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                scheduler.step()
                global_step += 1

                if global_step % 10 == 0:
                    pbar.set_postfix(loss=f"{accum_loss:.4f}", step=global_step)
                    accum_loss = 0.0
                if args.save_steps and global_step % args.save_steps == 0:
                    save_dir = Path(args.output_dir) / f"checkpoint-{global_step}"
                    model.save_pretrained(save_dir)
                    tokenizer.save_pretrained(save_dir)
            pbar.update(1)
        if seen_batches >= max_batches:
            break
        if global_step >= total_steps:
            break
    pbar.close()

    model.eval()
    losses = []
    with torch.no_grad():
        for batch in tqdm(eval_loader, desc="eval"):
            batch = {k: v.to(model.device) for k, v in batch.items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                losses.append(float(model(**batch).loss.detach().cpu()))
    eval_loss = sum(losses) / max(1, len(losses))

    final_dir = Path(args.output_dir) / "final_adapter"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    (Path(args.output_dir) / "train_summary.json").write_text(
        json.dumps(
            {
                "data": args.data,
                "model_dir": args.model_dir,
                "train_rows": len(train_rows),
                "eval_rows": len(eval_rows),
                "epochs": args.epochs,
                "global_step": global_step,
                "eval_loss": eval_loss,
                "rank": args.rank,
                "lr": args.lr,
                "max_length": args.max_length,
                "system_prompt": SYSTEM_PROMPT,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved {final_dir}")
    print(f"eval_loss={eval_loss:.4f}")


if __name__ == "__main__":
    main()
