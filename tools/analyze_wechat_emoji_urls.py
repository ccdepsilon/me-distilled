from __future__ import annotations

import csv
import html
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIRS = [
    Path(os.environ.get("ME_DISTILLED_STICKER_RAW_OUT", PROJECT_ROOT / "wechat_exports_txt_sticker_raw")),
    Path(os.environ.get("ME_DISTILLED_EXPORT_TXT", PROJECT_ROOT / "wechat_exports_txt")),
]
EMOTION_ROOT = Path(os.environ.get("ME_DISTILLED_EMOTION_OUT", PROJECT_ROOT / "wechat_emotions_export"))
EMOTION_DB = Path(os.environ.get("ME_DISTILLED_EMOTION_DB", PROJECT_ROOT / "wechat_decrypted" / "de_Emotion.db"))
EXPORTED_GIF_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_GIF_DIR", EMOTION_ROOT / "db_emotion_gif"))
OUT_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_ANALYSIS", EMOTION_ROOT / "analysis"))

EMOJI_RE = re.compile(r"<msg>\s*<emoji\b.*?</msg>|<emoji\b.*?</emoji>|<emoji\b[^>]*/>", re.IGNORECASE | re.DOTALL)


def parse_attrs(xml_text: str) -> dict[str, str] | None:
    text = html.unescape(xml_text)
    try:
        if not text.lstrip().startswith("<msg"):
            text = f"<msg>{text}</msg>"
        root = ET.fromstring(text)
        emoji = root.find("emoji") if root.tag.lower() != "emoji" else root
        if emoji is None:
            return None
        return {str(k).lower(): str(v) for k, v in emoji.attrib.items()}
    except ET.ParseError:
        attrs = dict(
            (key.lower(), value)
            for key, value in re.findall(r'([a-zA-Z0-9_]+)\s*=\s*"([^"]*)"', text)
        )
        return attrs or None


def load_db_md5s() -> set[str]:
    if not EMOTION_DB.exists():
        return set()
    conn = sqlite3.connect(str(EMOTION_DB))
    try:
        return {
            str(row[0]).lower()
            for row in conn.execute(
                "select MD5 from EmotionItem where Data is not null and length(Data) > 0"
            )
            if row[0]
        }
    finally:
        conn.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, str]] = []
    seen_chunks: set[str] = set()
    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for path in raw_dir.rglob("*.txt"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in EMOJI_RE.finditer(text):
                chunk = match.group(0)
                if chunk in seen_chunks:
                    continue
                seen_chunks.add(chunk)
                attrs = parse_attrs(chunk)
                if not attrs:
                    continue
                md5 = attrs.get("md5", "").lower()
                records.append(
                    {
                        "source_file": str(path),
                        "md5": md5,
                        "productid": attrs.get("productid", ""),
                        "cdnurl": attrs.get("cdnurl", ""),
                        "thumburl": attrs.get("thumburl", ""),
                        "encrypturl": attrs.get("encrypturl", ""),
                        "aeskey": attrs.get("aeskey", ""),
                        "externurl": attrs.get("externurl", ""),
                        "externmd5": attrs.get("externmd5", "").lower(),
                        "desc": attrs.get("desc", ""),
                        "width": attrs.get("width", ""),
                        "height": attrs.get("height", ""),
                    }
                )

    db_md5s = load_db_md5s()
    file_md5s = {p.stem.lower() for p in EXPORTED_GIF_DIR.glob("*") if p.is_file()}
    by_md5: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        if record["md5"]:
            by_md5[record["md5"]].append(record)

    summary_rows: list[dict[str, str | int]] = []
    for md5, items in sorted(by_md5.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        cdnurls = {item["cdnurl"] for item in items if item["cdnurl"]}
        thumburls = {item["thumburl"] for item in items if item["thumburl"]}
        encrypturls = {item["encrypturl"] for item in items if item["encrypturl"]}
        productids = {item["productid"] for item in items if item["productid"]}
        descs = {item["desc"] for item in items if item["desc"]}
        summary_rows.append(
            {
                "md5": md5,
                "count": len(items),
                "cdnurl_count": len(cdnurls),
                "thumburl_count": len(thumburls),
                "encrypturl_count": len(encrypturls),
                "productid_count": len(productids),
                "desc_count": len(descs),
                "in_emotion_db": int(md5 in db_md5s),
                "has_exported_gif": int(md5 in file_md5s),
                "sample_productid": next(iter(productids), ""),
                "sample_desc": next(iter(descs), ""),
                "sample_cdnurl": next(iter(cdnurls), ""),
                "sample_thumburl": next(iter(thumburls), ""),
            }
        )

    with (OUT_DIR / "emoji_records.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()) if records else ["md5"])
        writer.writeheader()
        writer.writerows(records)

    with (OUT_DIR / "emoji_md5_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()) if summary_rows else ["md5"])
        writer.writeheader()
        writer.writerows(summary_rows)

    products = Counter(record["productid"] or "(empty)" for record in records)
    print(f"records={len(records)}")
    print(f"unique_md5={len(by_md5)}")
    print("top_productids:")
    for productid, count in products.most_common(10):
        print(f"  {count}\t{productid}")
    print(f"out={OUT_DIR}")


if __name__ == "__main__":
    main()
