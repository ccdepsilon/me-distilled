from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import json
import os
import random
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECRYPTED = Path(os.environ.get("ME_DISTILLED_DECRYPTED", ROOT / "wechat_decrypted"))
DATA_DIR = Path(os.environ.get("ME_DISTILLED_DATA_DIR", ROOT / "distill_training_data"))
RAW_OUT = Path(os.environ.get("ME_DISTILLED_STICKER_RAW_OUT", ROOT / "wechat_exports_txt_sticker_raw"))
EMOJI_MAPPING = Path(os.environ.get("ME_DISTILLED_EMOJI_MAPPING", ROOT / "wechat_emotions_export" / "analysis" / "emoji_asset_mapping.csv"))
MANUAL_STICKER_MAPPING = Path(os.environ.get("ME_DISTILLED_MANUAL_STICKER_MAPPING", ROOT / "wechat_emotions_export" / "analysis" / "manual_sticker_mapping.json"))

SEED = 20260528
RNG = random.Random(SEED)

CONTACT_TARGETS: list[str] = []

if os.environ.get("ME_DISTILLED_CONTACTS_JSON"):
    CONTACT_TARGETS = json.loads(os.environ["ME_DISTILLED_CONTACTS_JSON"])

OUTPUT_CANDIDATES = DATA_DIR / "qa_with_stickers_candidates.jsonl"
OUTPUT_SAMPLED = DATA_DIR / "qa_with_stickers_sampled.jsonl"
OUTPUT_FINAL = DATA_DIR / "qa_with_stickers_sampled_with_synth.jsonl"
OUTPUT_TRAIN = DATA_DIR / "qa_with_stickers_train.jsonl"
REPORT = DATA_DIR / "qa_with_stickers_report.txt"

MAX_USER_CHARS = 160
MAX_ASSISTANT_VISIBLE_CHARS = 80
MAX_ASSISTANT_LINES = 4
MULTITURN_MAX_SPAN_SECONDS = 120
MULTITURN_TARGET_RATIO = 0.30
MULTITURN_MAX_MESSAGES = 6

TARGET_PURE_TEXT_RATIO = 0.68
TARGET_TEXT_STICKER_RATIO = 0.17
TARGET_PURE_STICKER_RATIO = 0.02
TARGET_UNICODE_RATIO = 0.10
MAX_TEXT_STICKER_PER_DESC = 24
MAX_PURE_STICKER_PER_DESC = 4
MAX_MULTITURN_STICKER_PER_DESC = 10
MAX_FINAL_STICKER_PER_DESC = 24
STICKER_DESC_LIMIT_OVERRIDES = {
    "嘻嘻": 3,
    "哈哈哈": 6,
    "拍飞": 3,
    "滑滑梯": 3,
}
ENABLE_STICKER = os.environ.get("ME_DISTILLED_ENABLE_STICKER", "1") != "0"
ENABLE_SYNTHETIC = os.environ.get("ME_DISTILLED_ENABLE_SYNTHETIC", "1") != "0"

SENSITIVE_TERMS = [*CONTACT_TARGETS]
if os.environ.get("ME_DISTILLED_SENSITIVE_JSON"):
    SENSITIVE_TERMS.extend(json.loads(os.environ["ME_DISTILLED_SENSITIVE_JSON"]))
SENSITIVE_RE = (
    re.compile("|".join(re.escape(item) for item in SENSITIVE_TERMS), re.IGNORECASE)
    if SENSITIVE_TERMS
    else re.compile(r"a\Ab")
)
URL_RE = re.compile(r"https?://|www\.|cdnurl=|thumburl=|encrypturl=", re.IGNORECASE)
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,12})\]")
EMOJI_XML_RE = re.compile(r"<msg>\s*<emoji\b.*?</msg>", re.IGNORECASE | re.DOTALL)
ANY_XML_RE = re.compile(r"<[^>]+>")
STICKER_RE = re.compile(r"<sticker:[^>]+>")
STICKER_NAME_RE = re.compile(r"<sticker:([^>]+)>")


WECHAT_BRACKET_EMOJI = {
    "微笑": "🙂",
    "撇嘴": "😒",
    "色": "😍",
    "发呆": "😐",
    "得意": "😎",
    "流泪": "😢",
    "害羞": "😊",
    "闭嘴": "🤐",
    "睡": "😴",
    "大哭": "😭",
    "尴尬": "😅",
    "发怒": "😠",
    "调皮": "😜",
    "呲牙": "😁",
    "惊讶": "😲",
    "难过": "😞",
    "酷": "😎",
    "冷汗": "😓",
    "抓狂": "😫",
    "吐": "🤮",
    "偷笑": "🤭",
    "愉快": "😄",
    "白眼": "🙄",
    "傲慢": "😤",
    "饥饿": "😋",
    "困": "😪",
    "惊恐": "😱",
    "流汗": "😅",
    "憨笑": "😄",
    "悠闲": "😌",
    "奋斗": "💪",
    "咒骂": "😡",
    "疑问": "🤔",
    "嘘": "🤫",
    "晕": "😵",
    "折磨": "😖",
    "衰": "😭",
    "骷髅": "☠️",
    "敲打": "🔨",
    "再见": "👋",
    "擦汗": "😅",
    "抠鼻": "🤢",
    "鼓掌": "👏",
    "糗大了": "😳",
    "坏笑": "😏",
    "左哼哼": "😤",
    "右哼哼": "😤",
    "哈欠": "🥱",
    "鄙视": "😒",
    "委屈": "🥺",
    "快哭了": "🥺",
    "阴险": "😈",
    "亲亲": "😘",
    "可怜": "🥺",
    "菜刀": "🔪",
    "西瓜": "🍉",
    "啤酒": "🍺",
    "篮球": "🏀",
    "乒乓": "🏓",
    "咖啡": "☕",
    "饭": "🍚",
    "猪头": "🐷",
    "玫瑰": "🌹",
    "凋谢": "🥀",
    "嘴唇": "💋",
    "爱心": "❤️",
    "心碎": "💔",
    "蛋糕": "🎂",
    "炸弹": "💣",
    "便便": "💩",
    "月亮": "🌙",
    "太阳": "☀️",
    "拥抱": "🤗",
    "强": "👍",
    "弱": "👎",
    "握手": "🤝",
    "胜利": "✌️",
    "抱拳": "🙏",
    "勾引": "🫴",
    "拳头": "✊",
    "OK": "👌",
    "跳跳": "🤸",
    "发抖": "🥶",
    "怄火": "😡",
    "转圈": "😵",
    "笑脸": "😄",
    "吃瓜": "🍉",
    "加油": "💪",
    "汗": "😅",
    "天啊": "😱",
    "Emm": "😶",
    "社会社会": "😎",
    "旺柴": "🐶",
    "好的": "👌",
    "打脸": "🤦",
    "加油加油": "💪",
    "哇": "😮",
    "翻白眼": "🙄",
    "666": "😎",
    "让我看看": "👀",
    "叹气": "😮‍💨",
    "苦涩": "🥲",
    "裂开": "🫠",
    "嘿哈": "😄",
    "捂脸": "🤦",
    "机智": "😏",
    "皱眉": "😟",
    "耶": "✌️",
    "红包": "🧧",
    "礼物": "🎁",
}


SYNTHETIC_ROWS = [
    ("这个说法还挺合理的", "确实"),
    ("感觉这样更方便一点", "确实"),
    ("他说得也不是没有道理", "确实"),
    ("这件事听起来就是这样", "确实"),
    ("我今天把作业写完了", "天哪"),
    ("这个通知写得好绕", "天哪"),
    ("他们居然现在才说", "天哪"),
    ("我刚发现还要再交一次", "天哪"),
    ("我刚知道这个安排", "原来如此"),
    ("所以是这么回事啊", "原来如此"),
    ("他刚刚又开始了", "呵呵"),
    ("他说自己一点问题都没有", "呵呵"),
    ("你在干嘛", "我在坐着"),
    ("你现在干什么呢", "我在坐着"),
    ("我今天考得还不错", "好厉害"),
    ("我终于把这个弄完了", "好厉害"),
    ("这个真的太抽象了", "笑死了"),
    ("他说完自己都沉默了", "笑死了"),
    ("那现在怎么办", "如何呢，又能怎"),
    ("这又能怎么样", "如何呢，又能怎"),
    ("他说这句话是什么意思", "啥意思"),
    ("这个通知到底想说什么", "啥意思"),
    ("我们专业今天又临时加活了", "这就是你们的优越之处"),
    ("我这个专业每天都很忙", "这就是你的优越之处"),
    ("我刚刚看到一个特别好笑的图", "笑死了 😭"),
    ("我今天真的有点崩溃", "天哪 😢"),
    ("这个东西居然一次过了", "好厉害 😎"),
    ("他刚才那句话也太离谱了", "呵呵 😅"),
    ("你看这个安排是不是很奇怪", "确实 🤦"),
    ("所以他最后还是没来", "原来如此 😐"),
]

for i in range(24):
    SYNTHETIC_ROWS.append((f"我觉得这个事情确实是第{i + 1}种情况", "确实"))
for i in range(24):
    SYNTHETIC_ROWS.append((f"我今天又遇到一个很离谱的事情{i + 1}", "天哪"))
for i in range(22):
    SYNTHETIC_ROWS.append((f"原来这个安排是这样{i + 1}", "原来如此"))
for i in range(20):
    SYNTHETIC_ROWS.append((f"他又在说自己完全没问题{i + 1}", "呵呵"))
for i in range(24):
    SYNTHETIC_ROWS.append((f"我刚刚看到一个很抽象的事情{i + 1}", "笑死了 😭"))
for i in range(24):
    SYNTHETIC_ROWS.append((f"今天这个消息真的有点突然{i + 1}", "天哪 😢"))
for i in range(20):
    SYNTHETIC_ROWS.append((f"这个结果比我想的顺利{i + 1}", "好厉害 😎"))


PURE_STICKER_SYNTHETIC_ROWS = [
    ("我真的一点都不想学习了", "<sticker:不想学习>"),
    ("你今天还学习吗", "<sticker:不想学习>"),
    ("快去看书", "<sticker:不想学习>"),
    ("你现在在干嘛", "<sticker:在玩洛克王国>"),
    ("你是不是又在玩游戏", "<sticker:在玩洛克王国>"),
    ("这个安排真的很离谱", "<sticker:好无语>"),
    ("他这个操作也太离谱了", "<sticker:好无语>"),
    ("你看看我这张照片", "<sticker:你好漂亮>"),
    ("我今天穿这套怎么样", "<sticker:你好漂亮>"),
    ("这个事情也太好笑了", "<sticker:嘻嘻>"),
    ("他刚才那句话笑死我了", "<sticker:哈哈哈>"),
    ("我今天真的有点崩溃", "<sticker:大哭>"),
    ("我刚刚被老师点名了", "<sticker:哭哭>"),
    ("那我先走了", "<sticker:拜拜>"),
    ("行那明天见", "<sticker:亲亲>"),
]

for i in range(8):
    user, assistant = PURE_STICKER_SYNTHETIC_ROWS[i % len(PURE_STICKER_SYNTHETIC_ROWS)]
    SYNTHETIC_ROWS.append((f"{user}{i + 1}", assistant))


MANUAL_STICKER_ROWS = [
    ("我真的一点都不想学习了", "不想学习 <sticker:不想学习>"),
    ("你今天学习了吗", "不想学习 <sticker:不想学习>"),
    ("快去学一会儿", "不想学习 <sticker:不想学习>"),
    ("我作业还没写完", "不想学习 <sticker:不想学习>"),
    ("你复习得怎么样了", "不想学习 <sticker:不想学习>"),
    ("明天考试你还不学吗", "不想学习 <sticker:不想学习>"),
    ("这节课真的听不下去了", "不想学习 <sticker:不想学习>"),
    ("我现在打开书就困", "不想学习 <sticker:不想学习>"),
    ("今天还要看专业课", "不想学习 <sticker:不想学习>"),
    ("你怎么又不学习", "不想学 <sticker:不想学习>"),
    ("这个知识点也太难背了", "不想学习 <sticker:不想学习>"),
    ("我看到课本就头大", "不想学习 <sticker:不想学习>"),
    ("你预习了吗", "不想学习 <sticker:不想学习>"),
    ("你是不是又在玩游戏", "在玩洛克王国 <sticker:在玩洛克王国>"),
    ("你现在没学习吧", "在玩洛克王国 <sticker:在玩洛克王国>"),
    ("你在忙什么", "我在坐着"),
    ("你现在有事吗", "我在坐着"),
    ("你人呢", "我在坐着"),
    ("你现在是不是没事", "我在坐着"),
    ("你刚刚在干嘛", "我在坐着"),
    ("你怎么不回消息", "我在坐着"),
    ("你是不是又在摸鱼", "我在坐着"),
    ("今天这个安排真的很离谱", "好无语 <sticker:好无语>"),
    ("他这个操作也太离谱了", "好无语 <sticker:好无语>"),
    ("我真的服了这个通知", "好无语 <sticker:好无语>"),
    ("他们怎么又临时改", "好无语 <sticker:好无语>"),
    ("这个课设要求写得像谜语", "好无语 <sticker:好无语>"),
    ("他又开始甩锅了", "好无语 <sticker:好无语>"),
    ("这人说话怎么这么离谱", "好无语 <sticker:好无语>"),
    ("我排了半天队结果说不能办", "好无语 <sticker:好无语>"),
    ("这个系统又崩了", "好无语 <sticker:好无语>"),
    ("老师突然又加了一个作业", "好无语 <sticker:好无语>"),
    ("这也太抽象了", "好无语 <sticker:好无语>"),
    ("他又在那边乱说", "好无语 <sticker:好无语>"),
    ("这个流程真的无敌麻烦", "好无语 <sticker:好无语>"),
    ("我今天拍了张照片", "你好漂亮 <sticker:你好漂亮>"),
    ("你看我这个自拍怎么样", "你好漂亮 <sticker:你好漂亮>"),
    ("我刚刚试了一下这个妆", "你好漂亮 <sticker:你好漂亮>"),
    ("这张照片好看吗", "你好漂亮 <sticker:你好漂亮>"),
    ("我今天穿这套怎么样", "你好漂亮 <sticker:你好漂亮>"),
    ("给你看一下我的新头像", "你好漂亮 <sticker:你好漂亮>"),
    ("我换了个发型", "你好漂亮 <sticker:你好漂亮>"),
    ("这张是不是还行", "你好漂亮 <sticker:你好漂亮>"),
    ("我朋友说这张不好看", "你好漂亮 <sticker:你好漂亮>"),
    ("你看看这个照片", "你好漂亮 <sticker:你好漂亮>"),
]


MANUAL_STICKER_ASSETS = {
    "不想学习": str(ROOT / "wechat_emotions_export" / "db_emotion_thumb" / "1.png"),
    "在玩洛克王国": str(ROOT / "wechat_emotions_export" / "db_emotion_thumb" / "2.png"),
    "好无语": str(ROOT / "wechat_emotions_export" / "db_emotion_thumb" / "3.png"),
    "你好漂亮": str(ROOT / "wechat_emotions_export" / "db_emotion_thumb" / "4.png"),
}


LOCAL_STICKER_DESC_CACHE: set[str] | None = None


MD5_DESC_CACHE: dict[str, str] | None = None


def load_md5_desc_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not EMOJI_MAPPING.exists():
        return mapping
    with EMOJI_MAPPING.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            md5 = str(row.get("md5") or "").lower()
            desc = str(row.get("parsed_desc") or "").strip()
            if md5 and desc:
                mapping[md5] = desc
    return mapping


def md5_desc_map() -> dict[str, str]:
    global MD5_DESC_CACHE
    if MD5_DESC_CACHE is None:
        MD5_DESC_CACHE = load_md5_desc_map()
    return MD5_DESC_CACHE


def local_sticker_descs() -> set[str]:
    global LOCAL_STICKER_DESC_CACHE
    if LOCAL_STICKER_DESC_CACHE is not None:
        return LOCAL_STICKER_DESC_CACHE

    descs = {desc for desc, path in MANUAL_STICKER_ASSETS.items() if Path(path).exists()}
    if EMOJI_MAPPING.exists():
        with EMOJI_MAPPING.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                desc = str(row.get("parsed_desc") or "").strip()
                if not desc:
                    continue
                for key in ("gif_path", "thumb_path"):
                    path = Path(str(row.get(key) or ""))
                    if path.exists() and path.suffix.lower() in {".gif", ".png", ".jpg", ".jpeg"}:
                        descs.add(desc)
                        break

    LOCAL_STICKER_DESC_CACHE = descs
    return descs


def normalize_sticker_desc(desc: str) -> str:
    desc = desc.strip()
    if not desc:
        return ""
    available = local_sticker_descs()
    if desc in available:
        return desc

    compact = re.sub(r"\s+", "", desc)
    for candidate in available:
        candidate_compact = re.sub(r"\s+", "", candidate)
        if compact and (
            compact == candidate_compact
            or compact in candidate_compact
            or candidate_compact in compact
        ):
            return candidate
    return ""


def normalize_sticker_tags(text: str) -> str:
    kept_one = False

    def repl(match: re.Match[str]) -> str:
        nonlocal kept_one
        desc = normalize_sticker_desc(match.group(1))
        if not desc or kept_one:
            return ""
        kept_one = True
        return f"<sticker:{desc}>"

    return normalize_spaces(STICKER_NAME_RE.sub(repl, text))


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def ts(value: object) -> str:
    try:
        ivalue = int(value)
    except Exception:
        return str(value)
    if ivalue > 10_000_000_000:
        ivalue //= 1000
    try:
        return dt.datetime.fromtimestamp(ivalue).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("select name from sqlite_master where type='table'")]


def cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"pragma table_info({table})")]


def load_contacts() -> list[dict]:
    con = sqlite3.connect(DECRYPTED / "de_MicroMsg.db")
    rows: list[dict] = []
    for table in tables(con):
        cs = cols(con, table)
        lowered = {c.lower(): c for c in cs}
        user_col = lowered.get("username")
        if not user_col:
            continue
        name_cols = [
            lowered.get(key)
            for key in (
                "nickname",
                "remark",
                "conremark",
                "alias",
                "reserved1",
                "reserved2",
                "remarkquanpin",
                "pyinitial",
                "quanpin",
            )
            if lowered.get(key)
        ]
        if not name_cols:
            continue
        select_cols = [user_col] + name_cols
        try:
            for row in con.execute(f"select {', '.join(select_cols)} from {table}"):
                wxid = clean_text(row[0])
                names = [clean_text(v) for v in row[1:] if clean_text(v)]
                if wxid and names:
                    rows.append({"wxid": wxid, "names": names, "table": table})
        except Exception:
            pass
    con.close()
    return rows


def match_targets() -> dict[str, dict | None]:
    contacts = [row for row in load_contacts() if not row["wxid"].endswith("@chatroom")]
    result: dict[str, dict | None] = {}
    for target in CONTACT_TARGETS:
        exact = []
        partial = []
        for row in contacts:
            haystack = [row["wxid"], *row["names"]]
            if any(target == value for value in haystack):
                exact.append(row)
            elif any(target in value or value in target for value in haystack if value):
                partial.append(row)
        candidates = exact or partial
        if not candidates:
            result[target] = None
            continue
        scored = []
        for row in candidates:
            msg_count = len(load_messages(row["wxid"]))
            exact_name = any(target == value for value in [row["wxid"], *row["names"]])
            scored.append((msg_count, exact_name, row))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result[target] = scored[0][2]
    return result


def message_dbs() -> list[Path]:
    dbs = sorted((DECRYPTED / "Multi").glob("de_MSG*.db"))
    for extra in ("de_ChatMsg.db", "de_OpenIMMsg.db"):
        path = DECRYPTED / extra
        if path.exists():
            dbs.append(path)
    return dbs


def load_messages(wxid: str) -> list[dict]:
    all_rows: list[dict] = []
    for db in message_dbs():
        con = sqlite3.connect(db)
        for table in tables(con):
            cs = cols(con, table)
            colset = set(cs)
            if not {"CreateTime", "IsSender", "StrContent"}.issubset(colset):
                continue
            talker_col = "StrTalker" if "StrTalker" in colset else "Talker" if "Talker" in colset else None
            if not talker_col:
                continue
            extra_cols = [c for c in ("Type", "SubType", "DisplayContent") if c in colset]
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


def parse_desc(desc: str) -> str:
    if not desc:
        return ""
    try:
        raw = base64.b64decode(desc + "=" * ((4 - len(desc) % 4) % 4))
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    pieces = re.findall(r"[\u4e00-\u9fffA-Za-z0-9！？?!，。~～、]{1,20}", text)
    for piece in pieces:
        if piece not in {"default", "zh_cn", "zh_tw"} and not piece.isascii():
            return piece
    return ""


def parse_emoji_attrs(xml_text: str) -> dict[str, str]:
    text = html.unescape(xml_text)
    try:
        root = ET.fromstring(text)
        emoji = root.find("emoji")
        if emoji is None:
            return {}
        return {str(k).lower(): str(v) for k, v in emoji.attrib.items()}
    except ET.ParseError:
        return {
            key.lower(): value
            for key, value in re.findall(r'([a-zA-Z0-9_]+)\s*=\s*"([^"]*)"', text)
        }


def sticker_from_xml(match: re.Match[str]) -> str:
    if not ENABLE_STICKER:
        return ""
    attrs = parse_emoji_attrs(match.group(0))
    desc = parse_desc(attrs.get("desc", ""))
    if not desc:
        desc = md5_desc_map().get(attrs.get("md5", "").lower(), "")
    desc = normalize_sticker_desc(desc)
    if not desc:
        return ""
    return f" <sticker:{desc}> "


def replace_brackets(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return WECHAT_BRACKET_EMOJI.get(key, "")

    return BRACKET_RE.sub(repl, text)


def normalize_spaces(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def clean_message_content(content: str) -> str:
    content = clean_text(content)
    if not content:
        return ""

    content = EMOJI_XML_RE.sub(sticker_from_xml, content)
    if ANY_XML_RE.search(STICKER_RE.sub("", content)):
        return ""
    content = replace_brackets(content)
    if URL_RE.search(content):
        return ""
    content = normalize_spaces(content)
    content = normalize_sticker_tags(content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def visible_text(value: str) -> str:
    value = STICKER_RE.sub("", value)
    value = re.sub(r"\s+", "", value)
    return value


def visible_len(value: str) -> int:
    return len(visible_text(value))


def nonempty_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def answer_type(answer: str) -> str:
    has_sticker = bool(STICKER_RE.search(answer))
    no_sticker = STICKER_RE.sub("", answer).strip()
    has_unicode = any(ord(ch) > 0xFFFF or ch in "🙂😐🤭😢😭🤦🥺🫠😅😄😎😒😮‍💨🥲👍👎🙏👌👀🍉🐶" for ch in no_sticker)
    has_cjk_or_ascii = bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", no_sticker))
    if has_sticker and not has_cjk_or_ascii and not has_unicode:
        return "pure_sticker"
    if has_sticker:
        return "text_sticker"
    if has_unicode and not has_cjk_or_ascii:
        return "pure_unicode"
    if has_unicode:
        return "text_unicode"
    return "pure_text"


def sticker_descs(answer: str) -> list[str]:
    return [item.strip() for item in STICKER_NAME_RE.findall(answer) if item.strip()]


def sticker_desc_limit(desc: str, default_limit: int) -> int:
    return STICKER_DESC_LIMIT_OVERRIDES.get(desc, default_limit)


def cap_sticker_desc_distribution(rows: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return rows
    kept: list[dict] = []
    counts: Counter[str] = Counter()
    for row in rows:
        descs = sticker_descs(row["messages"][-1]["content"])
        if not descs:
            kept.append(row)
            continue
        unique_descs = list(dict.fromkeys(descs))
        if any(counts[desc] >= sticker_desc_limit(desc, limit) for desc in unique_descs):
            continue
        for desc in unique_descs:
            counts[desc] += 1
        kept.append(row)
    return kept


def length_bucket(answer: str) -> str:
    length = visible_len(answer)
    if length <= 2:
        return "1-2"
    if length <= 5:
        return "3-5"
    if length <= 12:
        return "6-12"
    return "13+"


def length_sample_rate(answer: str) -> float:
    return {
        "1-2": 0.30,
        "3-5": 0.50,
        "6-12": 0.80,
        "13+": 1.00,
    }[length_bucket(answer)]


def reject_pair(user: str, assistant: str) -> str | None:
    if not user or not assistant:
        return "empty"
    if visible_len(user) > MAX_USER_CHARS:
        return "user_too_long"
    if visible_len(assistant) > MAX_ASSISTANT_VISIBLE_CHARS:
        return "assistant_too_long"
    if len(nonempty_lines(assistant)) > MAX_ASSISTANT_LINES:
        return "assistant_too_many_lines"
    joined = f"{user}\n{assistant}"
    if SENSITIVE_RE.search(joined):
        return "sensitive"
    if "晚安" in joined:
        return "good_night"
    joined_without_stickers = STICKER_RE.sub("", joined)
    if URL_RE.search(joined_without_stickers) or ANY_XML_RE.search(joined_without_stickers):
        return "bad_markup_or_url"
    return None


def merge_turns(messages: list[dict]) -> list[dict]:
    turns: list[dict] = []
    for row in messages:
        is_me = int(row.get("IsSender") or 0) == 1
        content = clean_message_content(row.get("StrContent") or row.get("DisplayContent") or "")
        if not content:
            continue
        if turns and turns[-1]["is_me"] == is_me:
            turns[-1]["content"] = normalize_spaces(f"{turns[-1]['content']}\n{content}")
            turns[-1]["count"] += 1
            try:
                turns[-1]["end_time"] = max(turns[-1]["end_time"], int(row.get("CreateTime") or 0))
            except Exception:
                pass
        else:
            try:
                create_time = int(row.get("CreateTime") or 0)
            except Exception:
                create_time = 0
            turns.append(
                {
                    "is_me": is_me,
                    "content": content,
                    "count": 1,
                    "start_time": create_time,
                    "end_time": create_time,
                }
            )
    return turns


def make_messages_row(messages: list[dict], source: str, synthetic: bool = False) -> dict:
    messages = [
        {
            "role": message["role"],
            "content": normalize_sticker_tags(str(message.get("content") or "")),
        }
        for message in messages
    ]
    assistant = str(messages[-1].get("content") or "")
    row = {
        "messages": messages,
        "meta": {
            "source": source,
            "answer_type": answer_type(assistant),
            "answer_length_bucket": length_bucket(assistant),
            "sample_kind": "multiturn" if len(messages) > 2 else "single_turn",
        },
    }
    if synthetic:
        row["meta"]["synthetic"] = True
    return row


def make_row(user: str, assistant: str, source: str, synthetic: bool = False) -> dict:
    return make_messages_row(
        [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        source,
        synthetic=synthetic,
    )


def reject_messages(messages: list[dict]) -> str | None:
    if len(messages) < 2:
        return "too_few_messages"
    if messages[-1]["role"] != "assistant":
        return "last_not_assistant"
    roles = [message["role"] for message in messages]
    if any(role not in {"user", "assistant"} for role in roles):
        return "bad_role"
    if any(roles[index] == roles[index - 1] for index in range(1, len(roles))):
        return "not_alternating"
    for message in messages:
        content = str(message.get("content") or "")
        if not content:
            return "empty"
        if message["role"] == "user" and visible_len(content) > MAX_USER_CHARS:
            return "user_too_long"
        if message["role"] == "assistant":
            if visible_len(content) > MAX_ASSISTANT_VISIBLE_CHARS:
                return "assistant_too_long"
            if len(nonempty_lines(content)) > MAX_ASSISTANT_LINES:
                return "assistant_too_many_lines"
    joined = "\n".join(str(message.get("content") or "") for message in messages)
    if SENSITIVE_RE.search(joined):
        return "sensitive"
    if "晚安" in joined:
        return "good_night"
    joined_without_stickers = STICKER_RE.sub("", joined)
    if URL_RE.search(joined_without_stickers) or ANY_XML_RE.search(joined_without_stickers):
        return "bad_markup_or_url"
    return None


def build_multiturn_rows(turns: list[dict], source: str) -> tuple[list[dict], Counter[str]]:
    rows: list[dict] = []
    rejects: Counter[str] = Counter()
    seen: set[tuple[str, ...]] = set()

    for end_index in range(len(turns)):
        if not turns[end_index]["is_me"]:
            continue
        for size in range(min(MULTITURN_MAX_MESSAGES, end_index + 1), 2, -1):
            start_index = end_index - size + 1
            window = turns[start_index : end_index + 1]
            if window[0]["is_me"]:
                continue
            span = int(window[-1].get("end_time") or 0) - int(window[0].get("start_time") or 0)
            if span < 0 or span > MULTITURN_MAX_SPAN_SECONDS:
                continue
            if any(window[i]["is_me"] == window[i - 1]["is_me"] for i in range(1, len(window))):
                continue
            messages = [
                {
                    "role": "assistant" if turn["is_me"] else "user",
                    "content": turn["content"],
                }
                for turn in window
            ]
            reason = reject_messages(messages)
            if reason:
                rejects[reason] += 1
                continue
            key = tuple(f"{message['role']}:{message['content']}" for message in messages)
            if key in seen:
                rejects["duplicate_multiturn"] += 1
                continue
            seen.add(key)
            row = make_messages_row(messages, source)
            row["meta"]["span_seconds"] = span
            rows.append(row)
            break

    return rows, rejects


def build_real_rows() -> tuple[list[dict], list[dict], list[str]]:
    RAW_OUT.mkdir(exist_ok=True)
    matched = match_targets()
    rows: list[dict] = []
    multiturn_rows: list[dict] = []
    match_report: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    reject_counts: Counter[str] = Counter()
    multiturn_reject_counts: Counter[str] = Counter()

    for target, contact in matched.items():
        if contact is None:
            match_report.append(f"{target}\tNOT_FOUND")
            continue
        wxid = contact["wxid"]
        display = next((name for name in contact["names"] if name), target)
        messages = load_messages(wxid)
        match_report.append(f"{target}\t{wxid}\t{display}\tmessages={len(messages)}")

        raw_path = RAW_OUT / f"{target}.txt"
        with raw_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"对象: {target}\nwxid: {wxid}\n消息数: {len(messages)}\n\n")
            for msg in messages:
                who = "我" if int(msg.get("IsSender") or 0) == 1 else display
                f.write(f"{ts(msg.get('CreateTime'))} {who}\n{clean_text(msg.get('StrContent'))}\n\n")

        turns = merge_turns(messages)
        contact_multiturn, contact_multiturn_rejects = build_multiturn_rows(turns, target)
        multiturn_rows.extend(contact_multiturn)
        multiturn_reject_counts.update(contact_multiturn_rejects)

        for prev, cur in zip(turns, turns[1:]):
            if prev["is_me"] or not cur["is_me"]:
                continue
            user = prev["content"]
            assistant = cur["content"]
            reason = reject_pair(user, assistant)
            if reason:
                reject_counts[reason] += 1
                continue
            pair = (user, assistant)
            if pair in seen_pairs:
                reject_counts["duplicate_pair"] += 1
                continue
            seen_pairs.add(pair)
            rows.append(make_row(user, assistant, target))

    match_report.append("")
    match_report.append("real_reject_counts:")
    match_report.extend(f"  {key}: {value}" for key, value in sorted(reject_counts.items()))
    match_report.append("")
    match_report.append("multiturn_reject_counts:")
    match_report.extend(f"  {key}: {value}" for key, value in sorted(multiturn_reject_counts.items()))
    return rows, multiturn_rows, match_report


def synthetic_rows() -> list[dict]:
    if not ENABLE_SYNTHETIC:
        return []
    rows = []
    seen = set()
    base_pairs = []
    for user, assistant in SYNTHETIC_ROWS:
        pair = (user, assistant)
        if pair in seen:
            continue
        seen.add(pair)
        base_pairs.append(pair)

    for user, assistant in base_pairs:
        rows.append(make_row(user, assistant, "synthetic", synthetic=True))

    for user, assistant in MANUAL_STICKER_ROWS:
        row = make_row(user, assistant, "manual_sticker_synthetic", synthetic=True)
        row["meta"]["manual_sticker"] = True
        rows.append(row)

    return rows


def sample_by_length(rows: list[dict]) -> tuple[list[dict], Counter[str]]:
    sampled = []
    dropped: Counter[str] = Counter()
    for row in rows:
        answer = row["messages"][1]["content"]
        bucket = length_bucket(answer)
        if row.get("meta", {}).get("manual_sticker") or row.get("meta", {}).get("synthetic"):
            sampled.append(row)
            continue
        if RNG.random() <= length_sample_rate(answer):
            sampled.append(row)
        else:
            dropped[bucket] += 1
    return sampled, dropped


def balance_expression_mix(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row["meta"]["answer_type"]].append(row)
    for values in buckets.values():
        RNG.shuffle(values)

    text_sticker_rows = cap_sticker_desc_distribution(
        buckets.get("text_sticker", []),
        MAX_TEXT_STICKER_PER_DESC,
    )
    pure_sticker_rows = cap_sticker_desc_distribution(
        buckets.get("pure_sticker", []),
        MAX_PURE_STICKER_PER_DESC,
    )
    pure_unicode_rows = buckets.get("pure_unicode", [])
    text_unicode_rows = buckets.get("text_unicode", [])
    unicode_rows = pure_unicode_rows + text_unicode_rows
    pure_text = buckets.get("pure_text", [])

    # Use pure text as the anchor so the final mix stays mostly text while
    # keeping sticker usage visible without making it dominate the target style.
    target_pure_text = min(
        len(pure_text),
        int(len(text_sticker_rows) * TARGET_PURE_TEXT_RATIO / TARGET_TEXT_STICKER_RATIO),
    )
    target_text_sticker = min(
        len(text_sticker_rows),
        int(target_pure_text * TARGET_TEXT_STICKER_RATIO / TARGET_PURE_TEXT_RATIO),
    )
    target_pure_sticker = min(
        len(pure_sticker_rows),
        int(target_pure_text * TARGET_PURE_STICKER_RATIO / TARGET_PURE_TEXT_RATIO),
    )
    target_unicode = min(
        len(unicode_rows),
        int(target_pure_text * TARGET_UNICODE_RATIO / TARGET_PURE_TEXT_RATIO),
    )

    selected_unicode = pure_unicode_rows[: min(len(pure_unicode_rows), target_unicode)]
    remaining_unicode = max(0, target_unicode - len(selected_unicode))
    selected_unicode += text_unicode_rows[:remaining_unicode]

    selected = (
        pure_text[:target_pure_text]
        + text_sticker_rows[:target_text_sticker]
        + pure_sticker_rows[:target_pure_sticker]
        + selected_unicode
    )
    RNG.shuffle(selected)
    stats = {
        "text_sticker_before_cap": len(text_sticker_rows),
        "text_sticker_after_cap": target_text_sticker,
        "pure_sticker_before_cap": len(pure_sticker_rows),
        "pure_sticker_after_cap": target_pure_sticker,
        "max_text_sticker_per_desc": MAX_TEXT_STICKER_PER_DESC,
        "max_pure_sticker_per_desc": MAX_PURE_STICKER_PER_DESC,
        "unicode_rows_before_cap": len(unicode_rows),
        "unicode_rows_after_cap": target_unicode,
        "pure_text_before_cap": len(pure_text),
        "pure_text_after_cap": target_pure_text,
        "target_pure_text_ratio_percent": int(TARGET_PURE_TEXT_RATIO * 100),
        "target_text_sticker_ratio_percent": int(TARGET_TEXT_STICKER_RATIO * 100),
        "target_pure_sticker_ratio_percent": int(TARGET_PURE_STICKER_RATIO * 100),
        "target_unicode_ratio_percent": int(TARGET_UNICODE_RATIO * 100),
    }
    return selected, stats


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_train_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps({"messages": row["messages"]}, ensure_ascii=False) + "\n")


def mix_multiturn_rows(single_rows: list[dict], multiturn_rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    multiturn_rows = cap_sticker_desc_distribution(multiturn_rows, MAX_MULTITURN_STICKER_PER_DESC)
    RNG.shuffle(multiturn_rows)
    target_multiturn = min(
        len(multiturn_rows),
        int(round(len(single_rows) * MULTITURN_TARGET_RATIO / (1 - MULTITURN_TARGET_RATIO))),
    )
    selected_multiturn = multiturn_rows[:target_multiturn]
    combined = single_rows + selected_multiturn
    RNG.shuffle(combined)
    return combined, {
        "single_rows_before_mix": len(single_rows),
        "multiturn_candidates": len(multiturn_rows),
        "multiturn_selected": len(selected_multiturn),
        "multiturn_target_ratio": int(MULTITURN_TARGET_RATIO * 100),
    }


def count_answer_types(rows: list[dict]) -> Counter[str]:
    return Counter(row["meta"]["answer_type"] for row in rows)


def count_length_buckets(rows: list[dict]) -> Counter[str]:
    return Counter(row["meta"]["answer_length_bucket"] for row in rows)


def count_final_sticker_descs(rows: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(sticker_descs(row["messages"][-1]["content"]))
    return counts


def cap_final_sticker_desc_distribution(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    kept: list[dict] = []
    counts: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    for row in rows:
        descs = sticker_descs(row["messages"][-1]["content"])
        if not descs:
            kept.append(row)
            continue
        unique_descs = list(dict.fromkeys(descs))
        blocked = [
            desc
            for desc in unique_descs
            if counts[desc] >= sticker_desc_limit(desc, MAX_FINAL_STICKER_PER_DESC)
        ]
        if blocked:
            dropped[blocked[0]] += 1
            continue
        for desc in unique_descs:
            counts[desc] += 1
        kept.append(row)
    return kept, {
        "final_sticker_cap_limit": MAX_FINAL_STICKER_PER_DESC,
        "final_sticker_cap_dropped": sum(dropped.values()),
        **{f"final_sticker_cap_dropped_{key}": value for key, value in dropped.most_common(20)},
    }


def percent(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "0.0%"


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    MANUAL_STICKER_MAPPING.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_STICKER_MAPPING.write_text(
        json.dumps(MANUAL_STICKER_ASSETS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    real_rows, multiturn_candidates, match_report = build_real_rows()
    synth = synthetic_rows()
    candidates = real_rows + synth
    write_jsonl(OUTPUT_CANDIDATES, candidates)

    sampled, length_dropped = sample_by_length(candidates)
    balanced, balance_stats = balance_expression_mix(sampled)
    final_rows, multiturn_mix_stats = mix_multiturn_rows(balanced, multiturn_candidates)
    final_rows, final_sticker_cap_stats = cap_final_sticker_desc_distribution(final_rows)
    write_jsonl(OUTPUT_SAMPLED, balanced)
    write_jsonl(OUTPUT_FINAL, final_rows)
    write_train_jsonl(OUTPUT_TRAIN, final_rows)

    type_counts = count_answer_types(final_rows)
    len_counts = count_length_buckets(final_rows)
    final_sticker_desc_counts = count_final_sticker_descs(final_rows)
    sticker_any = type_counts["text_sticker"] + type_counts["pure_sticker"]
    unicode_any = type_counts["text_unicode"] + type_counts["pure_unicode"]
    pure_text = type_counts["pure_text"]
    synthetic_count = sum(1 for row in final_rows if row["meta"].get("synthetic"))
    manual_sticker_count = sum(1 for row in final_rows if row["meta"].get("manual_sticker"))
    multiturn_count = sum(1 for row in final_rows if row["meta"].get("sample_kind") == "multiturn")

    report = [
        f"seed: {SEED}",
        f"candidates_output: {OUTPUT_CANDIDATES}",
        f"sampled_output: {OUTPUT_SAMPLED}",
        f"final_output: {OUTPUT_FINAL}",
        f"train_only_output: {OUTPUT_TRAIN}",
        f"raw_export_dir: {RAW_OUT}",
        f"manual_sticker_mapping: {MANUAL_STICKER_MAPPING}",
        "",
        "matched_contacts:",
        *match_report,
        "",
        f"real_candidate_rows: {len(real_rows)}",
        f"multiturn_candidate_rows: {len(multiturn_candidates)}",
        f"synthetic_candidate_rows: {len(synth)}",
        f"all_candidate_rows: {len(candidates)}",
        f"after_length_sampling: {len(sampled)}",
        f"after_expression_balance_single_turn_rows: {len(balanced)}",
        f"final_rows: {len(final_rows)}",
        f"synthetic_rows_in_final: {synthetic_count}",
        f"manual_sticker_rows_in_final: {manual_sticker_count}",
        f"multiturn_rows_in_final: {multiturn_count} ({percent(multiturn_count, len(final_rows))})",
        "",
        "length_sampling_dropped:",
        *[f"  {key}: {value}" for key, value in sorted(length_dropped.items())],
        "",
        "balance_stats:",
        *[f"  {key}: {value}" for key, value in sorted(balance_stats.items())],
        "",
        "multiturn_mix_stats:",
        *[f"  {key}: {value}" for key, value in sorted(multiturn_mix_stats.items())],
        "",
        "final_sticker_cap_stats:",
        *[f"  {key}: {value}" for key, value in sorted(final_sticker_cap_stats.items())],
        "",
        "answer_type_counts:",
        *[f"  {key}: {value} ({percent(value, len(final_rows))})" for key, value in sorted(type_counts.items())],
        f"  sticker_any: {sticker_any} ({percent(sticker_any, len(final_rows))})",
        f"  unicode_any: {unicode_any} ({percent(unicode_any, len(final_rows))})",
        "",
        "answer_length_buckets:",
        *[f"  {key}: {value}" for key, value in sorted(len_counts.items())],
        "",
        "top_sticker_desc_counts:",
        *[f"  {key}: {value}" for key, value in final_sticker_desc_counts.most_common(30)],
        "",
        "exact_synthetic_answer_counts:",
    ]
    exact = Counter(
        row["messages"][1]["content"]
        for row in final_rows
        if row["meta"].get("synthetic")
    )
    report.extend(f"  {key}: {value}" for key, value in exact.most_common())

    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
