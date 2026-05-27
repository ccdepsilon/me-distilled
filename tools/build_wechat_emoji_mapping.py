from __future__ import annotations

import csv
import base64
import json
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMOTION_ROOT = Path(os.environ.get("ME_DISTILLED_EMOTION_OUT", PROJECT_ROOT / "wechat_emotions_export"))
ANALYSIS_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_ANALYSIS", EMOTION_ROOT / "analysis"))
SUMMARY = ANALYSIS_DIR / "emoji_md5_summary.csv"
GIF_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_GIF_DIR", EMOTION_ROOT / "db_emotion_gif"))
THUMB_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_THUMB_DIR", EMOTION_ROOT / "db_emotion_thumb"))
RAW_DIR = Path(os.environ.get("ME_DISTILLED_EMOTION_RAW_DIR", EMOTION_ROOT / "raw_v1mm"))
OUT_CSV = Path(os.environ.get("ME_DISTILLED_EMOJI_MAPPING", ANALYSIS_DIR / "emoji_asset_mapping.csv"))
OUT_JSON = Path(os.environ.get("ME_DISTILLED_EMOJI_MAPPING_JSON", ANALYSIS_DIR / "emoji_asset_mapping.json"))


TEXT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9！？?!，。~～、]{1,20}")


def parse_desc(desc: str) -> str:
    if not desc:
        return ""
    try:
        raw = base64.b64decode(desc + "=" * ((4 - len(desc) % 4) % 4))
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    candidates = [
        item
        for item in TEXT_RE.findall(text)
        if item not in {"default", "zh_cn", "zh_tw"} and not item.isascii()
    ]
    if not candidates:
        return ""
    # Prefer the first Chinese text segment, usually zh_cn or default.
    return candidates[0]


def index_by_stem(directory: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not directory.exists():
        return index
    for path in directory.iterdir():
        if path.is_file():
            index.setdefault(path.stem.lower(), path)
            index.setdefault(path.name.lower(), path)
    return index


def main() -> None:
    rows = list(csv.DictReader(SUMMARY.open(encoding="utf-8-sig")))
    gif_index = index_by_stem(GIF_DIR)
    thumb_index = index_by_stem(THUMB_DIR)
    raw_index = index_by_stem(RAW_DIR)
    output = []

    for row in rows:
        md5 = row["md5"].lower()
        gif = gif_index.get(md5)
        thumb = thumb_index.get(md5)
        raw = raw_index.get(md5)
        asset_type = "remote_only"
        if gif:
            asset_type = "gif"
        elif raw:
            asset_type = "v1mm_raw"

        output.append(
            {
                "md5": md5,
                "count": int(row["count"]),
                "asset_type": asset_type,
                "gif_path": str(gif) if gif else "",
                "thumb_path": str(thumb) if thumb else "",
                "raw_v1mm_path": str(raw) if raw else "",
                "cdnurl": row["sample_cdnurl"],
                "thumburl": row["sample_thumburl"],
                "productid": row["sample_productid"],
                "desc": row["sample_desc"],
                "parsed_desc": parse_desc(row["sample_desc"]),
            }
        )

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output[0].keys()) if output else ["md5"])
        writer.writeheader()
        writer.writerows(output)

    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for row in output:
        counts[row["asset_type"]] = counts.get(row["asset_type"], 0) + 1

    print(f"rows={len(output)}")
    for key, value in sorted(counts.items()):
        print(f"{key}={value}")
    print(f"csv={OUT_CSV}")
    print(f"json={OUT_JSON}")


if __name__ == "__main__":
    main()
