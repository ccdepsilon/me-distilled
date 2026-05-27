from __future__ import annotations

import csv
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path


SOURCE = Path(
    os.environ.get(
        "ME_DISTILLED_CUSTOM_EMOTION",
        Path.home() / "Documents" / "WeChat Files" / "FileStorage" / "CustomEmotion",
    )
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("ME_DISTILLED_EMOTION_OUT", PROJECT_ROOT / "wechat_emotions_export"))
EMOTION_DB = Path(os.environ.get("ME_DISTILLED_EMOTION_DB", PROJECT_ROOT / "wechat_decrypted" / "de_Emotion.db"))

MAGICS = [
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webp"),
]


def detect_image(data: bytes) -> tuple[str | None, int]:
    for magic, ext in MAGICS:
        start = data.find(magic)
        if start >= 0:
            if ext == "webp" and data[start + 8 : start + 12] != b"WEBP":
                continue
            return ext, start
    return None, -1


def safe_name(path: Path, ext: str) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    return f"{path.name}_{digest}.{ext}"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUTPUT / "raw_v1mm"
    image_dir = OUTPUT / "images"
    db_gif_dir = OUTPUT / "db_emotion_gif"
    db_thumb_dir = OUTPUT / "db_emotion_thumb"
    raw_dir.mkdir(exist_ok=True)
    image_dir.mkdir(exist_ok=True)
    db_gif_dir.mkdir(exist_ok=True)
    db_thumb_dir.mkdir(exist_ok=True)

    rows: list[dict[str, str | int]] = []
    files = [p for p in SOURCE.rglob("*") if p.is_file()]

    for path in files:
        data = path.read_bytes()
        ext, offset = detect_image(data)

        row: dict[str, str | int] = {
            "source": str(path),
            "size": len(data),
            "head_hex": data[:16].hex(" "),
            "detected_ext": ext or "",
            "image_offset": offset,
            "exported": "",
        }

        if ext:
            out = image_dir / safe_name(path, ext)
            out.write_bytes(data[offset:])
            row["exported"] = str(out)
        else:
            out = raw_dir / path.name
            if not out.exists():
                shutil.copy2(path, out)
            row["exported"] = str(out)

        rows.append(row)

    with (OUTPUT / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["source", "size", "head_hex", "detected_ext", "image_offset", "exported"],
        )
        writer.writeheader()
        writer.writerows(rows)

    db_rows: list[dict[str, str | int]] = []
    if EMOTION_DB.exists():
        conn = sqlite3.connect(str(EMOTION_DB))
        try:
            for md5, data, thumb in conn.execute(
                "select MD5, Data, Thumb from EmotionItem where "
                "(Data is not null and length(Data) > 0) or "
                "(Thumb is not null and length(Thumb) > 0)"
            ):
                clean_md5 = str(md5).strip()
                if data:
                    ext, offset = detect_image(data)
                    ext = ext or "bin"
                    out = db_gif_dir / f"{clean_md5}.{ext}"
                    out.write_bytes(data[offset if offset >= 0 else 0 :])
                    db_rows.append(
                        {
                            "table": "EmotionItem",
                            "md5": clean_md5,
                            "kind": "data",
                            "size": len(data),
                            "detected_ext": ext,
                            "exported": str(out),
                        }
                    )
                if thumb:
                    ext, offset = detect_image(thumb)
                    ext = ext or "bin"
                    out = db_thumb_dir / f"{clean_md5}.{ext}"
                    out.write_bytes(thumb[offset if offset >= 0 else 0 :])
                    db_rows.append(
                        {
                            "table": "EmotionItem",
                            "md5": clean_md5,
                            "kind": "thumb",
                            "size": len(thumb),
                            "detected_ext": ext,
                            "exported": str(out),
                        }
                    )
        finally:
            conn.close()

    with (OUTPUT / "db_manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["table", "md5", "kind", "size", "detected_ext", "exported"],
        )
        writer.writeheader()
        writer.writerows(db_rows)

    image_count = sum(1 for row in rows if row["detected_ext"])
    db_data_count = sum(1 for row in db_rows if row["kind"] == "data")
    db_thumb_count = sum(1 for row in db_rows if row["kind"] == "thumb")
    print(f"source={SOURCE}")
    print(f"emotion_db={EMOTION_DB}")
    print(f"output={OUTPUT}")
    print(f"total={len(rows)}")
    print(f"decoded_images={image_count}")
    print(f"raw_v1mm={len(rows) - image_count}")
    print(f"db_emotion_gif={db_data_count}")
    print(f"db_emotion_thumb={db_thumb_count}")


if __name__ == "__main__":
    main()
