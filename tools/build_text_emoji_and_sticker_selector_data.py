from __future__ import annotations

import json
import os
import random
import re
from collections import Counter
from pathlib import Path

import build_sticker_training_data as base


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("ME_DISTILLED_DATA_DIR", ROOT / "distill_training_data"))
STICKER_MAP = Path(os.environ.get("ME_DISTILLED_STICKER_MAP", ROOT / "web-chat" / "app" / "sticker-map.json"))

SEED = 20260529
RNG = random.Random(SEED)

CHAT_CANDIDATES = DATA_DIR / "qa_text_emoji_candidates.jsonl"
CHAT_FINAL = DATA_DIR / "qa_text_emoji_train.jsonl"
STICKER_DATA = DATA_DIR / "sticker_selector_train.jsonl"
STICKER_LABELS = DATA_DIR / "sticker_selector_labels.json"
REPORT = DATA_DIR / "text_emoji_and_sticker_selector_report.txt"

NO_STICKER_LABEL = "__none__"
MAX_NONE_RATIO_TO_POSITIVE = 2.5
MAX_SELECTOR_TEXT_CHARS = 700
MAX_STICKER_PER_DESC = 80
MIN_STICKER_PER_DESC = 2

STICKER_RE = re.compile(r"<sticker:([^>]+)>")


def load_sticker_descs() -> set[str]:
    if not STICKER_MAP.exists():
        return set()
    data = json.loads(STICKER_MAP.read_text(encoding="utf-8"))
    return {str(key).strip() for key in data if str(key).strip()}


def strip_stickers(text: str) -> str:
    text = STICKER_RE.sub("", str(text or ""))
    text = base.normalize_spaces(text)
    return text.strip()


def clean_chat_row(row: dict) -> dict | None:
    messages = []
    for message in row["messages"]:
        content = strip_stickers(message.get("content", ""))
        if not content:
            return None
        messages.append({"role": message["role"], "content": content})

    reason = base.reject_messages(messages)
    if reason:
        return None
    assistant = messages[-1]["content"]
    return {
        "messages": messages,
        "meta": {
            **row.get("meta", {}),
            "answer_type": base.answer_type(assistant),
            "answer_length_bucket": base.length_bucket(assistant),
            "sticker_removed": bool(STICKER_RE.search(json.dumps(row["messages"], ensure_ascii=False))),
        },
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_train_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps({"messages": row["messages"]}, ensure_ascii=False) + "\n")


def sample_chat_rows(real_rows: list[dict], multiturn_rows: list[dict], synth_rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    synth_rows = [row for row in synth_rows if not row.get("meta", {}).get("manual_sticker")]
    single_candidates = real_rows + synth_rows
    sampled_single, length_dropped = base.sample_by_length(single_candidates)

    RNG.shuffle(multiturn_rows)
    target_multiturn = min(
        len(multiturn_rows),
        int(round(len(sampled_single) * base.MULTITURN_TARGET_RATIO / (1 - base.MULTITURN_TARGET_RATIO))),
    )
    combined = sampled_single + multiturn_rows[:target_multiturn]
    RNG.shuffle(combined)

    cleaned: list[dict] = []
    reject_counts: Counter[str] = Counter()
    seen: set[tuple[str, ...]] = set()
    for row in combined:
        cleaned_row = clean_chat_row(row)
        if cleaned_row is None:
            reject_counts["empty_after_sticker_strip_or_reject"] += 1
            continue
        key = tuple(f"{message['role']}:{message['content']}" for message in cleaned_row["messages"])
        if key in seen:
            reject_counts["duplicate_after_strip"] += 1
            continue
        seen.add(key)
        cleaned.append(cleaned_row)

    stats = {
        "single_candidates": len(single_candidates),
        "sampled_single": len(sampled_single),
        "multiturn_candidates": len(multiturn_rows),
        "multiturn_selected_before_clean": target_multiturn,
        "final_chat_rows": len(cleaned),
        **{f"length_dropped_{key}": value for key, value in sorted(length_dropped.items())},
        **{f"chat_reject_{key}": value for key, value in sorted(reject_counts.items())},
    }
    return cleaned, stats


def selector_text(messages: list[dict]) -> tuple[str, str]:
    history = messages[:-1]
    reply = strip_stickers(messages[-1]["content"])
    rendered = []
    for message in history:
        role = "我" if message["role"] == "assistant" else "对方"
        content = strip_stickers(message["content"])
        if content:
            rendered.append(f"{role}：{content}")
    context = "\n".join(rendered)[-MAX_SELECTOR_TEXT_CHARS:]
    text = f"上下文：\n{context}\n\n我的回复：{reply}".strip()
    return text, reply


def make_selector_rows(rows: list[dict], available_descs: set[str]) -> tuple[list[dict], dict[str, int]]:
    positive: list[dict] = []
    none_rows: list[dict] = []
    skipped: Counter[str] = Counter()
    per_desc: Counter[str] = Counter()

    for row in rows:
        messages = row["messages"]
        descs = [desc for desc in STICKER_RE.findall(messages[-1]["content"]) if desc in available_descs]
        text, reply = selector_text(messages)
        if not reply:
            skipped["empty_reply_after_strip"] += 1
            continue
        if not text:
            skipped["empty_text"] += 1
            continue
        if descs:
            desc = descs[0]
            if per_desc[desc] >= MAX_STICKER_PER_DESC:
                skipped["desc_cap"] += 1
                continue
            per_desc[desc] += 1
            positive.append(
                {
                    "text": text,
                    "label": desc,
                    "reply_text": reply,
                    "meta": {"source": row.get("meta", {}).get("source", ""), "sample_kind": row.get("meta", {}).get("sample_kind", "")},
                }
            )
        else:
            none_rows.append(
                {
                    "text": text,
                    "label": NO_STICKER_LABEL,
                    "reply_text": reply,
                    "meta": {"source": row.get("meta", {}).get("source", ""), "sample_kind": row.get("meta", {}).get("sample_kind", "")},
                }
            )

    label_counts = Counter(row["label"] for row in positive)
    positive = [row for row in positive if label_counts[row["label"]] >= MIN_STICKER_PER_DESC]
    label_counts = Counter(row["label"] for row in positive)

    none_target = min(len(none_rows), int(max(200, len(positive) * MAX_NONE_RATIO_TO_POSITIVE)))
    RNG.shuffle(none_rows)
    final_rows = positive + none_rows[:none_target]
    RNG.shuffle(final_rows)

    stats = {
        "selector_positive_rows": len(positive),
        "selector_none_candidates": len(none_rows),
        "selector_none_selected": none_target,
        "selector_final_rows": len(final_rows),
        "selector_labels_including_none": len(set(row["label"] for row in final_rows)),
        **{f"selector_skipped_{key}": value for key, value in sorted(skipped.items())},
    }
    return final_rows, stats


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    available_descs = load_sticker_descs()
    real_rows, multiturn_rows, match_report = base.build_real_rows()
    synth_rows = base.synthetic_rows()

    chat_rows, chat_stats = sample_chat_rows(real_rows, multiturn_rows, synth_rows)
    write_jsonl(CHAT_CANDIDATES, chat_rows)
    write_train_jsonl(CHAT_FINAL, chat_rows)

    selector_source = real_rows + multiturn_rows + [row for row in synth_rows if row.get("meta", {}).get("manual_sticker")]
    selector_rows, selector_stats = make_selector_rows(selector_source, available_descs)
    label_counts = Counter(row["label"] for row in selector_rows)
    labels = [NO_STICKER_LABEL] + sorted(label for label in label_counts if label != NO_STICKER_LABEL)
    STICKER_LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(STICKER_DATA, selector_rows)

    chat_type_counts = Counter(row["meta"]["answer_type"] for row in chat_rows)
    report = [
        f"seed: {SEED}",
        f"chat_train_output: {CHAT_FINAL}",
        f"selector_output: {STICKER_DATA}",
        f"selector_labels: {STICKER_LABELS}",
        f"available_sticker_descs: {len(available_descs)}",
        "",
        "matched_contacts:",
        *match_report,
        "",
        "chat_stats:",
        *[f"  {key}: {value}" for key, value in sorted(chat_stats.items())],
        "",
        "chat_answer_type_counts:",
        *[f"  {key}: {value}" for key, value in sorted(chat_type_counts.items())],
        "",
        "selector_stats:",
        *[f"  {key}: {value}" for key, value in sorted(selector_stats.items())],
        "",
        "top_selector_labels:",
        *[f"  {key}: {value}" for key, value in label_counts.most_common(40)],
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
