import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("ME_DISTILLED_DECRYPTED", PROJECT_ROOT / "wechat_decrypted"))
OUT_DIR = Path(os.environ.get("ME_DISTILLED_EXPORT_TXT", PROJECT_ROOT / "wechat_exports_txt"))

CONTACT_TARGETS: list[str] = []

if os.environ.get("ME_DISTILLED_CONTACTS_JSON"):
    CONTACT_TARGETS = json.loads(os.environ["ME_DISTILLED_CONTACTS_JSON"])

GROUP_TARGETS: list[str] = []

if os.environ.get("ME_DISTILLED_GROUPS_JSON"):
    GROUP_TARGETS = json.loads(os.environ["ME_DISTILLED_GROUPS_JSON"])


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\r\n]+', "_", name).strip() or "unknown"


def ts(value):
    try:
        value = int(value)
    except Exception:
        return str(value)
    if value > 10_000_000_000:
        value //= 1000
    try:
        return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def clean_text(text):
    if text is None:
        return ""
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def tables(con):
    return [r[0] for r in con.execute("select name from sqlite_master where type='table'").fetchall()]


def cols(con, table):
    return [r[1] for r in con.execute(f"pragma table_info({table})").fetchall()]


def decode_extra_name(raw):
    # Most name columns are plain text. Keep this hook small and conservative.
    return clean_text(raw)


def load_contacts():
    db = ROOT / "de_MicroMsg.db"
    con = sqlite3.connect(db)
    contact_rows = []
    for table in tables(con):
        cs = cols(con, table)
        lowered = {c.lower(): c for c in cs}
        user_col = lowered.get("username")
        if not user_col:
            continue
        name_cols = [
            c for key in ("nickname", "remark", "conremark", "alias", "reserved1", "reserved2", "remarkquanpin", "pyinitial", "quanpin")
            for c in [lowered.get(key)]
            if c
        ]
        if not name_cols:
            continue
        select_cols = [user_col] + name_cols
        try:
            for row in con.execute(f"select {', '.join(select_cols)} from {table}"):
                wxid = clean_text(row[0])
                names = [decode_extra_name(v) for v in row[1:] if decode_extra_name(v)]
                if wxid and names:
                    contact_rows.append({"table": table, "wxid": wxid, "names": names})
        except Exception:
            pass
    con.close()
    return contact_rows


def load_chatrooms():
    # Chatroom display names are often in ChatRoom table or Contact table.
    contacts = load_contacts()
    return [r for r in contacts if r["wxid"].endswith("@chatroom")]


def match_targets(rows, targets):
    matches = {}
    for target in targets:
        exact = []
        partial = []
        for row in rows:
            haystack = [row["wxid"], *row["names"]]
            if any(target == h for h in haystack):
                exact.append(row)
            elif any(target in h or h in target for h in haystack if h):
                partial.append(row)
        matches[target] = exact or partial
    return matches


def message_dbs():
    dbs = sorted((ROOT / "Multi").glob("de_MSG*.db"))
    chat = ROOT / "de_ChatMsg.db"
    if chat.exists():
        dbs.append(chat)
    openim = ROOT / "de_OpenIMMsg.db"
    if openim.exists():
        dbs.append(openim)
    return dbs


def load_messages(wxid):
    all_rows = []
    for db in message_dbs():
        try:
            con = sqlite3.connect(db)
        except Exception:
            continue
        for table in tables(con):
            cs = cols(con, table)
            colset = set(cs)
            if not {"CreateTime", "IsSender", "StrContent"}.issubset(colset):
                continue
            talker_col = "StrTalker" if "StrTalker" in colset else "Talker" if "Talker" in colset else None
            if not talker_col:
                continue
            extra_cols = []
            for c in ("Type", "SubType", "DisplayContent"):
                if c in colset:
                    extra_cols.append(c)
            select_cols = ["CreateTime", "IsSender", "StrContent", talker_col] + extra_cols
            sql = f"select {', '.join(select_cols)} from {table} where {talker_col} = ? order by CreateTime"
            try:
                for row in con.execute(sql, (wxid,)):
                    data = dict(zip(select_cols, row))
                    data["_db"] = str(db)
                    data["_table"] = table
                    all_rows.append(data)
            except Exception:
                pass
        con.close()
    all_rows.sort(key=lambda r: int(r.get("CreateTime") or 0))
    return all_rows


def render_message(row, display):
    is_sender = int(row.get("IsSender") or 0)
    who = "我" if is_sender else display
    content = clean_text(row.get("StrContent"))
    msg_type = row.get("Type")
    if not content:
        placeholders = {
            3: "[图片]",
            34: "[语音]",
            43: "[视频]",
            47: "[表情包]",
            49: clean_text(row.get("DisplayContent")) or "[分享/文件/引用消息]",
            10000: clean_text(row.get("DisplayContent")) or "[系统消息]",
        }
        try:
            content = placeholders.get(int(msg_type), f"[非文本消息 type={msg_type}]")
        except Exception:
            content = "[非文本消息]"
    return f"{ts(row.get('CreateTime'))} {who}\n{content}\n\n"


def export_one(label, wxid, display):
    rows = load_messages(wxid)
    path = OUT_DIR / f"{safe_name(label)}.txt"
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(f"对象: {label}\nwxid/chatroom: {wxid}\n消息数: {len(rows)}\n\n")
        for row in rows:
            f.write(render_message(row, display))
    return path, len(rows)


def pick_best(label, candidates):
    scored = []
    for row in candidates:
        count = len(load_messages(row["wxid"]))
        exact_name = label in row["names"] or label == row["wxid"]
        scored.append((count, exact_name, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2], scored[0][0]


def main():
    OUT_DIR.mkdir(exist_ok=True)
    contacts = load_contacts()
    contact_matches = match_targets([r for r in contacts if not r["wxid"].endswith("@chatroom")], CONTACT_TARGETS)
    group_matches = match_targets([r for r in contacts if r["wxid"].endswith("@chatroom")], GROUP_TARGETS)

    report = []
    for label, candidates in {**contact_matches, **group_matches}.items():
        if not candidates:
            report.append((label, "NOT_FOUND", "", 0, ""))
            continue
        row, _ = pick_best(label, candidates)
        display = next((n for n in row["names"] if n), label)
        path, count = export_one(label, row["wxid"], display)
        report.append((label, row["wxid"], display, count, str(path)))

    report_path = OUT_DIR / "_export_report.txt"
    with report_path.open("w", encoding="utf-8", newline="") as f:
        for item in report:
            f.write("\t".join(map(str, item)) + "\n")
    print(report_path)
    for item in report:
        print(item)


if __name__ == "__main__":
    main()
