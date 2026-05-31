import os

os.environ["PYTORCH_ENABLE_META_DEVICE_IMPORT"] = "0"
os.environ["PYTHONIOENCODING"] = "utf-8"

import argparse
import json
import math
import random
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import DataLoader, Dataset
from tqdm.auto import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, get_cosine_schedule_with_warmup


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


TOKENIZER_FILES = ("tokenizer_config.json", "tokenizer.json", "tokenizer.model", "vocab.json", "merges.txt")
MODEL_WEIGHT_FILES = (
    "model.safetensors",
    "model.safetensors.index.json",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
)


def has_tokenizer_files(path: Path) -> bool:
    return any((path / name).exists() for name in TOKENIZER_FILES)


def has_model_weights(path: Path) -> bool:
    return any((path / name).exists() for name in MODEL_WEIGHT_FILES) or any(path.glob("*.safetensors")) or any(path.glob("*.bin"))


def find_tokenizer_dir(model_dir: Path, search_root: Path) -> Path | None:
    current = model_dir
    while True:
        if has_tokenizer_files(current):
            return current
        if current == search_root or current.parent == current:
            break
        current = current.parent

    matches = [candidate.parent for name in TOKENIZER_FILES for candidate in search_root.rglob(name)]
    if matches:
        matches = sorted(set(matches), key=lambda item: (len(item.relative_to(search_root).parts), str(item).lower()))
        return matches[0]
    return None


def resolve_model_paths(path: Path) -> tuple[Path, Path]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"model_dir does not exist: {path}")
    if path.is_file():
        raise NotADirectoryError(f"model_dir must be a directory, got file: {path}")

    def looks_like_model_dir(candidate: Path) -> bool:
        return (candidate / "config.json").exists() and has_model_weights(candidate)

    if looks_like_model_dir(path):
        model_dir = path
        tokenizer_dir = find_tokenizer_dir(model_dir, path)
        if tokenizer_dir is None:
            raise FileNotFoundError(f"Could not find tokenizer files under {path}. Expected one of: {', '.join(TOKENIZER_FILES)}")
        return model_dir, tokenizer_dir

    common_children = [
        "model",
        "models",
        "Qwen2.5-7B-Instruct",
        "qwen2.5-7b-instruct",
        "snapshots",
    ]
    for child in common_children:
        candidate = path / child
        if candidate.exists() and looks_like_model_dir(candidate):
            tokenizer_dir = find_tokenizer_dir(candidate, path)
            if tokenizer_dir is None:
                raise FileNotFoundError(f"Could not find tokenizer files under {path}. Expected one of: {', '.join(TOKENIZER_FILES)}")
            return candidate, tokenizer_dir

    matches = [candidate for candidate in path.rglob("config.json") if looks_like_model_dir(candidate.parent)]
    if matches:
        matches.sort(key=lambda item: (len(item.parent.relative_to(path).parts), str(item.parent).lower()))
        model_dir = matches[0].parent
        tokenizer_dir = find_tokenizer_dir(model_dir, path)
        if tokenizer_dir is None:
            raise FileNotFoundError(f"Could not find tokenizer files under {path}. Expected one of: {', '.join(TOKENIZER_FILES)}")
        return model_dir, tokenizer_dir

    raise FileNotFoundError(
        f"Could not find a Hugging Face/Transformers model directory under {path}. "
        "Expected config.json plus model weight files. If this is a ModelScope cache root, "
        "pass the nested snapshot/model directory or update the download path."
    )


def resolve_model_dir(path: Path) -> Path:
    return resolve_model_paths(path)[0]


def first_real_device(model) -> torch.device:
    for parameter in model.parameters():
        if parameter.device.type != "meta":
            return parameter.device
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


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
    parser.add_argument("--load_in_4bit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--gradient_checkpointing", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    model_dir, tokenizer_dir = resolve_model_paths(Path(args.model_dir))
    if str(model_dir) != str(Path(args.model_dir).expanduser().resolve()):
        print(f"resolved_model_dir: {model_dir}")
    if tokenizer_dir != model_dir:
        print(f"resolved_tokenizer_dir: {tokenizer_dir}")

    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir), trust_remote_code=True, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    rows = read_jsonl(Path(args.data))
    train_rows, eval_rows = split_rows(rows, args.seed, args.eval_size)

    quantization_config = None
    if args.load_in_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir),
        torch_dtype=None if args.load_in_4bit else torch.float16,
        quantization_config=quantization_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    if args.load_in_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=args.gradient_checkpointing)
    elif args.gradient_checkpointing:
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
    if len(train_ds) == 0:
        raise RuntimeError("No trainable rows after tokenization. Increase --max_length or check data.")
    collator = Collator(tokenizer)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collator)
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collator)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    total_steps = math.ceil(len(train_loader) * args.epochs / args.grad_accum)
    warmup_steps = max(10, total_steps // 20)
    scheduler = get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps)
    use_cuda = torch.cuda.is_available()
    autocast_device = "cuda" if use_cuda else "cpu"
    input_device = first_real_device(model)
    scaler = torch.amp.GradScaler("cuda", enabled=use_cuda)

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
            batch = {k: v.to(input_device) for k, v in batch.items()}
            with torch.autocast(device_type=autocast_device, dtype=torch.float16, enabled=use_cuda):
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
            batch = {k: v.to(input_device) for k, v in batch.items()}
            with torch.autocast(device_type=autocast_device, dtype=torch.float16, enabled=use_cuda):
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
                "resolved_model_dir": str(model_dir),
                "resolved_tokenizer_dir": str(tokenizer_dir),
                "load_in_4bit": args.load_in_4bit,
                "gradient_checkpointing": args.gradient_checkpointing,
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
