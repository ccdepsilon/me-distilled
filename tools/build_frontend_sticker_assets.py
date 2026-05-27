from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EMOJI_MAPPING = Path(os.environ.get("ME_DISTILLED_EMOJI_MAPPING", ROOT / "wechat_emotions_export" / "analysis" / "emoji_asset_mapping.csv"))
MANUAL_MAPPING = Path(os.environ.get("ME_DISTILLED_MANUAL_STICKER_MAPPING", ROOT / "wechat_emotions_export" / "analysis" / "manual_sticker_mapping.json"))
PUBLIC_DIR = Path(os.environ.get("ME_DISTILLED_STICKER_PUBLIC_DIR", ROOT / "web-chat" / "public" / "stickers"))
OUT_JSON = Path(os.environ.get("ME_DISTILLED_STICKER_MAP", ROOT / "web-chat" / "app" / "sticker-map.json"))
IMAGE_EXTS = {".gif", ".png", ".jpg", ".jpeg"}


def copy_asset(desc: str, source: Path, mapping: dict[str, str]) -> None:
    if not desc or not source.exists() or source.suffix.lower() not in IMAGE_EXTS:
        return
    target = PUBLIC_DIR / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    mapping[desc] = f"/stickers/{target.name}"


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for path in PUBLIC_DIR.iterdir():
        if path.is_file():
            path.unlink()

    mapping: dict[str, str] = {}

    if MANUAL_MAPPING.exists():
        manual = json.loads(MANUAL_MAPPING.read_text(encoding="utf-8"))
        for desc, source in manual.items():
            copy_asset(str(desc).strip(), Path(str(source)), mapping)

    if EMOJI_MAPPING.exists():
        rows = list(csv.DictReader(EMOJI_MAPPING.open(encoding="utf-8-sig", newline="")))
        rows.sort(key=lambda row: int(row.get("count") or 0), reverse=True)
        for row in rows:
            desc = str(row.get("parsed_desc") or "").strip()
            if not desc or desc in mapping:
                continue
            for key in ("gif_path", "thumb_path"):
                source = Path(str(row.get(key) or ""))
                if source.exists() and source.suffix.lower() in IMAGE_EXTS:
                    copy_asset(desc, source, mapping)
                    break

    OUT_JSON.write_text(
        json.dumps(dict(sorted(mapping.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"stickers={len(mapping)}")
    print(f"public_dir={PUBLIC_DIR}")
    print(f"map={OUT_JSON}")


if __name__ == "__main__":
    main()
