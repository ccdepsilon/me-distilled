from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("ME_DISTILLED_DATA_DIR", ROOT / "distill_training_data"))
INPUT = Path(os.environ.get("ME_DISTILLED_EMOJI_TAG_INPUT", DATA_DIR / "qa_text_emoji_train.jsonl"))
OUTPUT = Path(os.environ.get("ME_DISTILLED_EMOJI_TAG_OUTPUT", DATA_DIR / "qa_text_emoji_tag_train.jsonl"))
REPORT = Path(os.environ.get("ME_DISTILLED_EMOJI_TAG_REPORT", DATA_DIR / "qa_text_emoji_tag_report.txt"))


EMOJI_TO_TAG = {
    "🙂": "微笑",
    "😐": "无语",
    "🤭": "偷笑",
    "😢": "流泪",
    "😭": "大哭",
    "🤦‍♀️": "捂脸",
    "🤦‍♂️": "捂脸",
    "🤦": "捂脸",
    "🥺": "委屈",
    "🫠": "融化",
    "😅": "尴尬",
    "😄": "笑",
    "😁": "呲牙",
    "😂": "笑哭",
    "🤣": "笑死",
    "😍": "喜欢",
    "😘": "亲亲",
    "🥰": "可爱",
    "😎": "酷",
    "😒": "撇嘴",
    "😮‍💨": "叹气",
    "😮": "惊讶",
    "😤": "生气",
    "😡": "发怒",
    "🥲": "苦笑",
    "👍": "强",
    "👎": "弱",
    "🙏": "拜托",
    "👌": "OK",
    "👀": "看看",
    "🍉": "吃瓜",
    "🐶": "狗头",
    "❤️": "爱心",
    "❤": "爱心",
    "💔": "心碎",
    "💪": "加油",
    "👏": "鼓掌",
    "🤔": "疑问",
    "😴": "睡觉",
    "😳": "发呆",
    "☺️": "害羞",
    "😋": "馋",
}

DEFAULT_IDENTITY_QUESTIONS = [
    "你是谁",
    "你是谁啊",
    "你到底是谁",
    "你叫什么",
    "你是什么人",
    "你是哪个",
    "你知道你是谁吗",
    "你能不能介绍一下你自己",
    "你是什么模型",
    "那你说说你是谁",
    "你别装了你是谁",
    "你不会不知道你是谁吧",
]


def read_json_list_from_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        values = [item.strip() for item in raw.split("|")]
    return [str(item).strip() for item in values if str(item).strip()]


IDENTITY_QUESTIONS = read_json_list_from_env(
    "ME_DISTILLED_IDENTITY_QUESTIONS_JSON",
    DEFAULT_IDENTITY_QUESTIONS,
)
IDENTITY_ANSWERS = read_json_list_from_env("ME_DISTILLED_IDENTITY_ANSWERS_JSON", [])

TAG_RE = re.compile(r"<emoji:([^>]+)>")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def replace_emoji(text: str, counts: Counter[str]) -> str:
    result = str(text or "")
    for emoji, desc in sorted(EMOJI_TO_TAG.items(), key=lambda item: len(item[0]), reverse=True):
        if emoji in result:
            counts[desc] += result.count(emoji)
            result = result.replace(emoji, f" <emoji:{desc}> ")
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r" *\n *", "\n", result)
    return result.strip()


def transform_row(row: dict, counts: Counter[str]) -> dict:
    messages = []
    for message in row["messages"]:
        messages.append(
            {
                "role": message["role"],
                "content": replace_emoji(str(message.get("content") or ""), counts),
            }
        )
    return {"messages": messages}


def identity_rows() -> list[dict]:
    rows = []
    if not IDENTITY_ANSWERS:
        return rows
    for question in IDENTITY_QUESTIONS:
        for answer in IDENTITY_ANSWERS:
            rows.append(
                {
                    "messages": [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ]
                }
            )
    return rows


def main() -> None:
    rows = read_jsonl(INPUT)
    emoji_counts: Counter[str] = Counter()
    transformed = [transform_row(row, emoji_counts) for row in rows]

    existing_identity = Counter()
    for row in transformed:
        assistant = row["messages"][-1]["content"]
        if assistant in IDENTITY_ANSWERS:
            existing_identity[assistant] += 1

    final_rows = transformed + identity_rows()
    write_jsonl(OUTPUT, final_rows)

    tag_rows = 0
    pure_tag_rows = 0
    for row in final_rows:
        assistant = row["messages"][-1]["content"].strip()
        if TAG_RE.search(assistant):
            tag_rows += 1
            if TAG_RE.sub("", assistant).strip() == "":
                pure_tag_rows += 1

    final_identity = Counter()
    same_question_pairs = Counter()
    for row in final_rows:
        user = row["messages"][-2]["content"] if len(row["messages"]) >= 2 else ""
        assistant = row["messages"][-1]["content"]
        if assistant in IDENTITY_ANSWERS:
            final_identity[assistant] += 1
            same_question_pairs[user] += 1

    report = [
        f"input: {INPUT}",
        f"output: {OUTPUT}",
        f"input_rows: {len(rows)}",
        f"output_rows: {len(final_rows)}",
        f"added_identity_rows: {len(IDENTITY_QUESTIONS) * len(IDENTITY_ANSWERS)}",
        f"emoji_tag_rows: {tag_rows}",
        f"pure_emoji_tag_rows: {pure_tag_rows}",
        "",
        "emoji_replacements:",
        *[f"  {key}: {value}" for key, value in emoji_counts.most_common()],
        "",
        "identity_counts_before_extra:",
        *[f"  {key}: {value}" for key, value in existing_identity.items()],
        "",
        "identity_counts_after_extra:",
        *[f"  {key}: {value}" for key, value in final_identity.items()],
        "",
        "identity_question_answer_counts:",
        *[f"  {key}: {value}" for key, value in same_question_pairs.items() if key in IDENTITY_QUESTIONS],
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
