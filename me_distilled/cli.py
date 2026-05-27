from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / ".cache" / "me-distilled"
TOOLS_CACHE = CACHE_DIR / "tools"
MODEL_CACHE = CACHE_DIR / "models"

WECHATMSG_URLS = [
    "https://github.com/LC044/WeChatMsg.git",
    "https://ghfast.top/github.com/LC044/WeChatMsg.git",
]
LLAMA_CPP_URLS = [
    "https://github.com/ggml-org/llama.cpp.git",
    "https://ghfast.top/github.com/ggml-org/llama.cpp.git",
]

HF_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
MODELSCOPE_MODEL_ID = "qwen/Qwen2.5-7B-Instruct"
GGUF_REPO_ID = "bartowski/Qwen2.5-7B-Instruct-GGUF"
GGUF_FILENAME = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"

SYSTEM_PROMPT = (
    "你是一个中文微信聊天模型，模仿“我”的聊天方式和语气。你正在和朋友微信聊天。"
    "请参考前面的上下文，但只回复最后一条用户消息。如果提供了相关记忆，可以参考这些信息，但不要生硬复述。"
    "回复要自然、简短，像朋友微信聊天。不要像 AI 助手，不要讲大道理，不要主动总结，不要列举建议，"
    "不要替用户继续说话，不要续写完整聊天记录。可以一条或多条短句回复；如果多条短句，用换行分开。"
)


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
except Exception:  # pragma: no cover - fallback for minimal installs
    Console = None  # type: ignore
    Panel = None  # type: ignore
    Table = None  # type: ignore
    console = None


@dataclass
class RunState:
    run: str
    created_at: str
    steps: dict[str, bool] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


def out(message: str = "", style: str | None = None) -> None:
    if console:
        console.print(message, style=style)
    else:
        print(message)


def heading(title: str, body: str | None = None) -> None:
    if console and Panel:
        console.print(Panel(body or "", title=title, expand=False))
    else:
        print(f"\n== {title} ==")
        if body:
            print(body)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_lines(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def new_run_name() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in RUNS_DIR.glob(f"{stamp}-*") if p.is_dir())
    return f"{stamp}-{len(existing) + 1:03d}"


def ensure_run(run: str | None = None, resume: str | None = None) -> tuple[Path, RunState]:
    run_dir = Path(resume) if resume else RUNS_DIR / (run or new_run_name())
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    for sub in [
        "logs",
        "exports/txt",
        "exports/txt_sticker_raw",
        "stickers/public",
        "stickers/emotion_export",
        "data",
        "model",
    ]:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "status.json"
    if state_path.exists():
        raw = read_json(state_path, {})
        state = RunState(
            run=raw.get("run", run_dir.name),
            created_at=raw.get("created_at", dt.datetime.now().astimezone().isoformat()),
            steps=raw.get("steps", {}),
            paths=raw.get("paths", {}),
            config=raw.get("config", {}),
        )
    else:
        state = RunState(run=run_dir.name, created_at=dt.datetime.now().astimezone().isoformat())
    save_state(run_dir, state)
    return run_dir, state


def save_state(run_dir: Path, state: RunState) -> None:
    write_json(run_dir / "status.json", asdict(state))


def mark(run_dir: Path, state: RunState, step: str, value: bool = True) -> None:
    state.steps[step] = value
    save_state(run_dir, state)


def prompt_text(question: str, default: str = "", *, required: bool = False, auto_yes: bool = False) -> str:
    if auto_yes and default:
        out(f"{question} [{default}] -> {default}", "dim")
        return default
    while True:
        suffix = f" [{default}]" if default else ""
        answer = input(f"{question}{suffix}: ").strip()
        if answer:
            return answer
        if default or not required:
            return default
        out("这里必须填写。", "yellow")


def prompt_yes(question: str, default: bool = True, *, auto_yes: bool = False) -> bool:
    if auto_yes:
        out(f"{question} -> {'是' if default else '否'}", "dim")
        return default
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{question} [{suffix}] ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true", "是", "好", "继续"}


def prompt_choice(question: str, options: list[str], default: int = 1, *, auto_yes: bool = False) -> int:
    if auto_yes:
        out(f"{question} -> {options[default - 1]}", "dim")
        return default
    out("")
    out(question, "bold")
    for idx, option in enumerate(options, 1):
        out(f"  {idx}. {option}")
    answer = input(f"请选择 [{default}]: ").strip()
    if not answer:
        return default
    try:
        value = int(answer)
    except ValueError:
        return default
    return min(max(value, 1), len(options))


def run_command(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    log: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cwd.mkdir(parents=True, exist_ok=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    out(f"\n$ {' '.join(cmd)}", "cyan")
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"\n\n$ {' '.join(cmd)}\n")
            proc = subprocess.run(cmd, cwd=cwd, env=merged_env, text=True, stdout=f, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.run(cmd, cwd=cwd, env=merged_env, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def install_requirements(path: Path) -> None:
    if not path.exists():
        out(f"未找到依赖文件: {path}", "red")
        raise SystemExit(1)
    run_command([sys.executable, "-m", "pip", "install", "-r", str(path)])


def clone_with_fallback(urls: list[str], target: Path, name: str) -> Path:
    if target.exists() and (target / ".git").exists():
        out(f"已发现 {name}: {target}", "green")
        return target
    if target.exists() and any(target.iterdir()):
        out(f"目录已存在，复用: {target}", "green")
        return target
    if not command_exists("git"):
        out("未找到 git，请先安装 Git，或手动下载后用参数指定目录。", "red")
        raise SystemExit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error = 0
    for url in urls:
        proc = run_command(["git", "clone", "--depth", "1", url, str(target)], check=False)
        if proc.returncode == 0:
            out(f"{name} 下载完成: {target}", "green")
            return target
        last_error = proc.returncode
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        out(f"{name} 下载失败，自动切换备用源。", "yellow")
    raise SystemExit(last_error or 1)


def check_db(decrypted: Path) -> dict[str, Any]:
    msg_dir = decrypted / "Multi"
    msg_dbs = sorted(msg_dir.glob("de_MSG*.db")) if msg_dir.exists() else []
    result = {
        "micro_msg": (decrypted / "de_MicroMsg.db").exists(),
        "emotion": (decrypted / "de_Emotion.db").exists(),
        "msg_dbs": [str(path) for path in msg_dbs],
    }
    result["ok"] = bool(result["micro_msg"] and result["msg_dbs"])
    return result


def sqlite_tables(db: Path) -> list[str]:
    con = sqlite3.connect(db)
    try:
        return [row[0] for row in con.execute("select name from sqlite_master where type='table'")]
    finally:
        con.close()


def contacts_from_db(decrypted: Path, include_groups: bool = False) -> list[dict[str, str]]:
    db = decrypted / "de_MicroMsg.db"
    if not db.exists():
        return []
    rows: list[dict[str, str]] = []
    con = sqlite3.connect(db)
    try:
        for table in sqlite_tables(db):
            cols = [row[1] for row in con.execute(f"pragma table_info({table})")]
            lower = {col.lower(): col for col in cols}
            user_col = lower.get("username")
            if not user_col:
                continue
            name_cols = [
                lower.get(key)
                for key in ("nickname", "remark", "conremark", "alias", "reserved1", "reserved2")
                if lower.get(key)
            ]
            if not name_cols:
                continue
            select_cols = [user_col, *name_cols]
            try:
                for raw in con.execute(f"select {', '.join(select_cols)} from {table}"):
                    wxid = str(raw[0] or "").strip()
                    if not wxid:
                        continue
                    is_group = wxid.endswith("@chatroom")
                    if is_group and not include_groups:
                        continue
                    names = [str(item or "").strip() for item in raw[1:] if str(item or "").strip()]
                    if names:
                        rows.append({"wxid": wxid, "name": names[0], "aliases": " / ".join(names)})
            except sqlite3.Error:
                continue
    finally:
        con.close()
    dedup: dict[str, dict[str, str]] = {}
    for row in rows:
        dedup.setdefault(row["wxid"], row)
    return list(dedup.values())


def message_count(decrypted: Path, wxid: str) -> int:
    total = 0
    for db in (decrypted / "Multi").glob("de_MSG*.db"):
        con = sqlite3.connect(db)
        try:
            for table in sqlite_tables(db):
                cols = {row[1].lower(): row[1] for row in con.execute(f"pragma table_info({table})")}
                talker_col = cols.get("strtalker") or cols.get("talker")
                if not talker_col:
                    continue
                try:
                    total += int(con.execute(f"select count(*) from {table} where {talker_col} = ?", (wxid,)).fetchone()[0])
                except sqlite3.Error:
                    continue
        finally:
            con.close()
    return total


def match_contacts(decrypted: Path, targets: list[str], include_groups: bool = False) -> list[dict[str, Any]]:
    contacts = contacts_from_db(decrypted, include_groups=include_groups)
    result: list[dict[str, Any]] = []
    for target in targets:
        candidates = [
            item
            for item in contacts
            if target == item["wxid"] or target in item["name"] or target in item["aliases"]
        ]
        if not candidates:
            result.append({"target": target, "status": "missing", "wxid": "", "name": "", "count": 0})
            continue
        candidates.sort(key=lambda row: (target == row["name"], target in row["name"]), reverse=True)
        chosen = candidates[0]
        result.append(
            {
                "target": target,
                "status": "ok",
                "wxid": chosen["wxid"],
                "name": chosen["name"],
                "count": message_count(decrypted, chosen["wxid"]),
            }
        )
    return result


def find_wechat_files() -> list[Path]:
    roots = [
        Path.home() / "Documents" / "WeChat Files",
        Path.home() / "Documents" / "Weixin Files",
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_dir() and (path / "FileStorage").exists():
                candidates.append(path)
    return candidates


def env_for_run(
    run_dir: Path,
    decrypted: Path,
    contacts: list[str],
    groups: list[str] | None = None,
    *,
    sticker: bool = True,
    synthetic: bool = False,
    identity_answers: list[str] | None = None,
) -> dict[str, str]:
    emotion_out = run_dir / "stickers" / "emotion_export"
    sensitive_terms = read_lines(run_dir / "sensitive_words.txt")
    return {
        "PYTHONUTF8": "1",
        "ME_DISTILLED_DECRYPTED": str(decrypted),
        "ME_DISTILLED_CONTACTS_JSON": json.dumps(contacts, ensure_ascii=False),
        "ME_DISTILLED_GROUPS_JSON": json.dumps(groups or [], ensure_ascii=False),
        "ME_DISTILLED_EXPORT_TXT": str(run_dir / "exports" / "txt"),
        "ME_DISTILLED_STICKER_RAW_OUT": str(run_dir / "exports" / "txt_sticker_raw"),
        "ME_DISTILLED_DATA_DIR": str(run_dir / "data"),
        "ME_DISTILLED_EMOTION_OUT": str(emotion_out),
        "ME_DISTILLED_EMOTION_ANALYSIS": str(emotion_out / "analysis"),
        "ME_DISTILLED_EMOTION_DB": str(decrypted / "de_Emotion.db"),
        "ME_DISTILLED_EMOJI_MAPPING": str(emotion_out / "analysis" / "emoji_asset_mapping.csv"),
        "ME_DISTILLED_EMOJI_MAPPING_JSON": str(emotion_out / "analysis" / "emoji_asset_mapping.json"),
        "ME_DISTILLED_MANUAL_STICKER_MAPPING": str(emotion_out / "analysis" / "manual_sticker_mapping.json"),
        "ME_DISTILLED_STICKER_PUBLIC_DIR": str(run_dir / "stickers" / "public"),
        "ME_DISTILLED_STICKER_MAP": str(run_dir / "stickers" / "sticker-map.json"),
        "ME_DISTILLED_ENABLE_STICKER": "1" if sticker else "0",
        "ME_DISTILLED_ENABLE_SYNTHETIC": "1" if synthetic else "0",
        "ME_DISTILLED_SENSITIVE_JSON": json.dumps(sensitive_terms, ensure_ascii=False),
        "ME_DISTILLED_IDENTITY_ANSWERS_JSON": json.dumps(identity_answers or [], ensure_ascii=False),
    }


def ensure_wechatmsg() -> Path:
    return clone_with_fallback(WECHATMSG_URLS, TOOLS_CACHE / "WeChatMsg", "WeChatMsg")


def ensure_llama_cpp() -> Path:
    path = clone_with_fallback(LLAMA_CPP_URLS, TOOLS_CACHE / "llama.cpp", "llama.cpp")
    req = path / "requirements.txt"
    if req.exists() and not module_exists("sentencepiece"):
        out("正在安装 llama.cpp 转换依赖。", "cyan")
        run_command([sys.executable, "-m", "pip", "install", "-r", str(req)])
    return path


def ensure_hf_model(path: Path | None = None) -> Path | None:
    target = path or MODEL_CACHE / "Qwen2.5-7B-Instruct"
    if target.exists() and any(target.iterdir()):
        out(f"已发现 HF/ModelScope 基座: {target}", "green")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    out("正在下载 Qwen2.5-7B-Instruct。优先 ModelScope，失败后切 Hugging Face。", "cyan")
    if module_exists("modelscope"):
        try:
            os.environ.setdefault("MODELSCOPE_CACHE", str(MODEL_CACHE / "modelscope"))
            from modelscope import snapshot_download

            downloaded = Path(snapshot_download(MODELSCOPE_MODEL_ID, cache_dir=str(MODEL_CACHE / "modelscope")))
            out(f"ModelScope 下载完成: {downloaded}", "green")
            return downloaded
        except Exception as exc:
            out(f"ModelScope 下载失败: {exc}", "yellow")
    else:
        out("未安装 modelscope，跳过国内源。可运行 `me-distilled setup deps --kind cli`。", "yellow")
    if module_exists("huggingface_hub"):
        try:
            from huggingface_hub import snapshot_download

            downloaded = Path(snapshot_download(HF_MODEL_ID, local_dir=str(target), local_dir_use_symlinks=False))
            out(f"Hugging Face 下载完成: {downloaded}", "green")
            return downloaded
        except Exception as exc:
            out(f"Hugging Face 下载失败: {exc}", "yellow")
    out("基座自动下载失败。请手动下载后用 --base 指定目录。", "red")
    return None


def ensure_base_gguf(path: Path | None = None) -> Path | None:
    target = path or MODEL_CACHE / GGUF_FILENAME
    if target.exists() and target.stat().st_size > 1_000_000:
        out(f"已发现 GGUF 基座: {target}", "green")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if not module_exists("huggingface_hub"):
        out("未安装 huggingface-hub，无法自动下载 GGUF。", "yellow")
        return None
    out("正在下载 Qwen2.5-7B-Instruct Q4_K_M GGUF。", "cyan")
    try:
        from huggingface_hub import hf_hub_download

        downloaded = Path(hf_hub_download(GGUF_REPO_ID, GGUF_FILENAME, local_dir=str(target.parent)))
        out(f"GGUF 下载完成: {downloaded}", "green")
        return downloaded
    except Exception as exc:
        out(f"GGUF 自动下载失败: {exc}", "yellow")
        out("请手动下载 Qwen2.5-7B-Instruct-Q4_K_M.gguf 后用 --base-gguf 指定。", "yellow")
        return None


def doctor_lines() -> list[tuple[str, str, str]]:
    checks: list[tuple[str, str, str]] = []
    checks.append(("Python", sys.version.split()[0], "OK" if sys.version_info >= (3, 10) else "需要 >=3.10"))
    checks.append(("OS", platform.platform(), "OK"))
    for name in ["git", "ollama", "node", "npm"]:
        checks.append((name, shutil.which(name) or "未找到", "OK" if command_exists(name) else "可稍后安装"))
    if command_exists("nvidia-smi"):
        proc = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True, capture_output=True)
        gpu = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "NVIDIA GPU"
        checks.append(("GPU", gpu, "OK"))
    else:
        checks.append(("GPU", "未检测到 nvidia-smi", "训练 7B 不推荐"))
    for module in ["torch", "transformers", "peft", "modelscope", "huggingface_hub"]:
        checks.append((f"python:{module}", "installed" if module_exists(module) else "missing", "OK" if module_exists(module) else "可自动安装"))
    return checks


def command_doctor(_args: argparse.Namespace) -> None:
    heading("环境检查")
    rows = doctor_lines()
    if console and Table:
        table = Table(show_header=True, header_style="bold")
        table.add_column("项目")
        table.add_column("结果")
        table.add_column("说明")
        for row in rows:
            table.add_row(*row)
        console.print(table)
    else:
        for item, value, note in rows:
            print(f"{item}: {value} ({note})")


def command_setup_deps(args: argparse.Namespace) -> None:
    if args.kind in {"cli", "all"}:
        install_requirements(ROOT / "requirements-cli.txt")
    if args.kind in {"train", "all"}:
        install_requirements(ROOT / "requirements-train-cu121.txt")


def command_setup_tools(args: argparse.Namespace) -> None:
    if args.wechatmsg or args.all:
        ensure_wechatmsg()
    if args.llama_cpp or args.all:
        ensure_llama_cpp()


def command_setup_models(args: argparse.Namespace) -> None:
    if args.hf or args.all:
        ensure_hf_model(Path(args.base) if args.base else None)
    if args.gguf or args.all:
        ensure_base_gguf(Path(args.base_gguf) if args.base_gguf else None)


def command_wechat_decrypt(args: argparse.Namespace) -> None:
    tool = Path(args.tool) if args.tool else ensure_wechatmsg()
    req = tool / "requirements.txt"
    if req.exists() and prompt_yes("是否为 WeChatMsg 安装/更新依赖？", True, auto_yes=args.yes):
        run_command([sys.executable, "-m", "pip", "install", "-r", str(req)], cwd=tool)
    main_py = tool / "main.py"
    if not main_py.exists():
        out(f"未找到 WeChatMsg main.py: {main_py}", "red")
        raise SystemExit(1)
    out("即将打开 WeChatMsg。请在工具中完成数据库解密，输出目录建议选择本项目的 wechat_decrypted。", "yellow")
    subprocess.Popen([sys.executable, str(main_py)], cwd=tool)
    out("WeChatMsg 已启动。完成解密后运行：")
    out("  me-distilled wechat check --decrypted ./wechat_decrypted", "cyan")


def command_wechat_check(args: argparse.Namespace) -> None:
    decrypted = Path(args.decrypted)
    result = check_db(decrypted)
    heading("微信数据库检查", f"目录: {decrypted}")
    out(f"de_MicroMsg.db: {'OK' if result['micro_msg'] else 'missing'}")
    out(f"de_Emotion.db: {'OK' if result['emotion'] else 'missing'}")
    out(f"de_MSG*.db: {len(result['msg_dbs'])}")
    if not result["ok"]:
        out("检查失败：至少需要 de_MicroMsg.db 和 Multi/de_MSG*.db。", "red")
        raise SystemExit(1)
    out("检查通过。", "green")


def command_wechat_match(args: argparse.Namespace) -> None:
    targets = read_lines(Path(args.contacts))
    matches = match_contacts(Path(args.decrypted), targets, include_groups=args.include_groups)
    for item in matches:
        status = "[OK]" if item["status"] == "ok" else "[MISS]"
        out(f"{status} {item['target']} -> {item['name']} / {item['wxid']} / {item['count']} 条")
    if args.out:
        write_json(Path(args.out), matches)


def command_wechat_export(args: argparse.Namespace) -> None:
    contacts = read_lines(Path(args.contacts))
    groups = read_lines(Path(args.groups)) if args.groups else []
    run_dir, state = ensure_run(args.run, args.resume)
    decrypted = Path(args.decrypted)
    env = env_for_run(run_dir, decrypted, contacts, groups)
    run_command([sys.executable, "-X", "utf8", "tools/export_selected_wechat_txt.py"], env=env)
    state.paths["decrypted"] = str(decrypted)
    state.paths["contacts"] = str(Path(args.contacts))
    mark(run_dir, state, "wechat_exported")


def command_sticker_export(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    decrypted = Path(args.decrypted)
    wechat_files = Path(args.wechat_files) if args.wechat_files else None
    if not wechat_files:
        candidates = find_wechat_files()
        if candidates:
            wechat_files = candidates[0]
            out(f"自动选择微信 Files 目录: {wechat_files}", "green")
    if not wechat_files or not wechat_files.exists():
        out("未找到微信 Files 目录，请用 --wechat-files 指定到 .../WeChat Files/<wxid>。", "red")
        raise SystemExit(1)
    env = env_for_run(run_dir, decrypted, [])
    env["ME_DISTILLED_CUSTOM_EMOTION"] = str(wechat_files / "FileStorage" / "CustomEmotion")
    run_command([sys.executable, "-X", "utf8", "tools/export_wechat_emotions.py"], env=env)
    run_command([sys.executable, "-X", "utf8", "tools/build_wechat_emoji_mapping.py"], env=env)
    mark(run_dir, state, "stickers_exported")


def command_sticker_map(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    env = env_for_run(run_dir, Path(args.decrypted), [])
    run_command([sys.executable, "-X", "utf8", "tools/build_frontend_sticker_assets.py"], env=env)
    mark(run_dir, state, "sticker_map_built")


def command_data_build(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    contacts = read_lines(Path(args.contacts))
    groups = read_lines(Path(args.groups)) if args.groups else []
    identity_answers = [item for item in args.identity_answer if item.strip()]
    env = env_for_run(
        run_dir,
        Path(args.decrypted),
        contacts,
        groups,
        sticker=not args.no_sticker,
        synthetic=args.synthetic,
        identity_answers=identity_answers,
    )
    run_command([sys.executable, "-X", "utf8", "tools/build_sticker_training_data.py"], env=env, log=run_dir / "logs" / "data-build.log")
    final_data = run_dir / "data" / "qa_with_stickers_train.jsonl"
    if args.mode in {"text-emoji", "text-emoji-tag"}:
        run_command(
            [sys.executable, "-X", "utf8", "tools/build_text_emoji_and_sticker_selector_data.py"],
            env=env,
            log=run_dir / "logs" / "text-emoji-build.log",
        )
        final_data = run_dir / "data" / "qa_text_emoji_train.jsonl"
    if args.mode == "text-emoji-tag":
        run_command(
            [sys.executable, "-X", "utf8", "tools/make_emoji_tag_training_data.py"],
            env=env,
            log=run_dir / "logs" / "emoji-tag-build.log",
        )
        final_data = run_dir / "data" / "qa_text_emoji_tag_train.jsonl"
    state.paths["train_data"] = str(final_data)
    state.config["data_mode"] = args.mode
    mark(run_dir, state, "data_built")
    out(f"训练数据: {final_data}", "green")
    command_data_report(argparse.Namespace(data=str(final_data), out=str(run_dir / "data" / "report.summary.txt"), sticker_map=str(run_dir / "stickers" / "sticker-map.json")))


def command_data_report(args: argparse.Namespace) -> None:
    data = Path(args.data)
    if not data.exists():
        out(f"未找到数据文件: {data}", "red")
        raise SystemExit(1)
    rows = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines() if line.strip()]
    import re

    sticker_re = re.compile(r"<sticker:([^>]+)>")
    emoji_tag_re = re.compile(r"<emoji:([^>]+)>")
    sticker_map = read_json(Path(args.sticker_map), {}) if args.sticker_map and Path(args.sticker_map).exists() else {}
    stats = {
        "total": len(rows),
        "multiturn": 0,
        "sticker_any": 0,
        "emoji_tag_any": 0,
        "missing_sticker": 0,
        "long_answer_gt_80": 0,
    }
    for row in rows:
        messages = row.get("messages", [])
        if len(messages) > 2:
            stats["multiturn"] += 1
        answer = str(messages[-1].get("content", "")) if messages else ""
        descs = sticker_re.findall(answer)
        if descs:
            stats["sticker_any"] += 1
            stats["missing_sticker"] += sum(1 for desc in descs if sticker_map and desc not in sticker_map)
        if emoji_tag_re.search(answer):
            stats["emoji_tag_any"] += 1
        if len(answer) > 80:
            stats["long_answer_gt_80"] += 1
    total = max(1, stats["total"])
    lines = [f"{key}: {value} ({value / total * 100:.1f}%)" for key, value in stats.items()]
    heading("数据报告", "\n".join(lines))
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_default_train_data(run_dir: Path) -> Path:
    for name in ["qa_text_emoji_tag_train.jsonl", "qa_text_emoji_train.jsonl", "qa_with_stickers_train.jsonl"]:
        path = run_dir / "data" / name
        if path.exists():
            return path
    raise SystemExit(f"未找到训练数据，请先运行 data build: {run_dir / 'data'}")


def command_train_lora(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    base = Path(args.base) if args.base else ensure_hf_model(None)
    if not base:
        raise SystemExit(1)
    data = Path(args.data) if args.data else find_default_train_data(run_dir)
    out_dir = Path(args.output) if args.output else run_dir / "model" / "lora"
    if not module_exists("torch") or not module_exists("transformers") or not module_exists("peft"):
        out("缺少训练依赖。请先运行：me-distilled setup deps --kind train", "red")
        raise SystemExit(1)
    if command_exists("nvidia-smi"):
        out("检测到 NVIDIA 环境，开始本地 LoRA 训练。", "green")
    else:
        out("未检测到 nvidia-smi。7B 本地训练可能非常慢或失败。", "yellow")
    cmd = [
        sys.executable,
        "-X",
        "utf8",
        "tools/remote_train_lora_context.py",
        "--model_dir",
        str(base),
        "--data",
        str(data),
        "--output_dir",
        str(out_dir),
        "--max_length",
        str(args.max_length),
        "--epochs",
        str(args.epochs),
        "--batch_size",
        str(args.batch_size),
        "--grad_accum",
        str(args.grad_accum),
        "--lr",
        str(args.lr),
        "--rank",
        str(args.rank),
        "--alpha",
        str(args.alpha),
        "--dropout",
        str(args.dropout),
        "--seed",
        str(args.seed),
        "--eval_size",
        str(args.eval_size),
        "--save_steps",
        str(args.save_steps),
    ]
    run_command(cmd, log=run_dir / "logs" / "train.log")
    state.paths["hf_base"] = str(base)
    state.paths["train_data"] = str(data)
    state.paths["lora"] = str(out_dir / "final_adapter")
    mark(run_dir, state, "trained")


def command_convert_adapter(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    base = Path(args.base) if args.base else Path(state.paths.get("hf_base", ""))
    if not base.exists():
        base = ensure_hf_model(None) or base
    llama = Path(args.llama_cpp) if args.llama_cpp else ensure_llama_cpp()
    script = llama / "convert_lora_to_gguf.py"
    if not script.exists():
        out(f"未找到转换脚本: {script}", "red")
        raise SystemExit(1)
    adapter = Path(args.adapter) if args.adapter else run_dir / "model" / "lora" / "final_adapter"
    out_path = Path(args.out) if args.out else run_dir / "model" / "adapter.gguf"
    run_command([sys.executable, "-X", "utf8", str(script), str(adapter), "--base", str(base), "--outfile", str(out_path)])
    state.paths["adapter_gguf"] = str(out_path)
    mark(run_dir, state, "adapter_gguf_created")


def write_modelfile(path: Path, base_gguf: Path, adapter_gguf: Path, model_name: str) -> None:
    text = f'''FROM {base_gguf.as_posix()}
ADAPTER {adapter_gguf.as_posix()}

TEMPLATE """{{{{ if .Messages }}}}{{{{ range .Messages }}}}<|im_start|>{{{{ .Role }}}}
{{{{ .Content }}}}<|im_end|>
{{{{ end }}}}<|im_start|>assistant
{{{{ else }}}}<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
{{{{ end }}}}{{{{ .Response }}}}"""

SYSTEM """{SYSTEM_PROMPT}"""

PARAMETER temperature 0.2
PARAMETER top_p 0.75
PARAMETER repeat_penalty 1.15
PARAMETER num_ctx 4096
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
'''
    path.write_text(text, encoding="utf-8")
    out(f"已写入 Modelfile: {path} ({model_name})", "green")


def command_ollama_create(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    if not command_exists("ollama"):
        out("未找到 Ollama。请先安装 Ollama 并确认 `ollama --version` 可用。", "red")
        raise SystemExit(1)
    base_gguf = Path(args.base_gguf) if args.base_gguf else ensure_base_gguf(None)
    if not base_gguf:
        raise SystemExit(1)
    adapter = Path(args.adapter) if args.adapter else Path(state.paths.get("adapter_gguf", run_dir / "model" / "adapter.gguf"))
    if not adapter.exists():
        out(f"未找到 adapter GGUF: {adapter}", "red")
        raise SystemExit(1)
    modelfile = run_dir / "Modelfile"
    write_modelfile(modelfile, base_gguf, adapter, args.name)
    run_command(["ollama", "create", args.name, "-f", str(modelfile)])
    state.paths["base_gguf"] = str(base_gguf)
    state.paths["modelfile"] = str(modelfile)
    state.config["ollama_model"] = args.name
    mark(run_dir, state, "ollama_created")


def ollama_chat(model: str, text: str, temperature: float = 0.2) -> str:
    body = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": text}],
        "options": {"temperature": temperature, "top_p": 0.75, "repeat_penalty": 1.15, "num_predict": 80},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload.get("message", {}).get("content", payload.get("response", ""))).strip()


def command_ollama_test(args: argparse.Namespace) -> None:
    cases = args.prompt or ["你在干嘛", "你是谁", "我今天好累"]
    for case in cases:
        out(f"\n用户：{case}", "bold")
        try:
            out("模型：" + ollama_chat(args.model, case, args.temperature), "green")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            out(f"测试失败：{exc}", "red")
            raise SystemExit(1)


def command_web_prepare(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    web = Path(args.web_dir)
    app_map = web / "app" / "sticker-map.json"
    public_stickers = web / "public" / "stickers"
    app_map.parent.mkdir(parents=True, exist_ok=True)
    public_stickers.mkdir(parents=True, exist_ok=True)
    for path in public_stickers.iterdir():
        if path.is_file():
            path.unlink()
    run_map = run_dir / "stickers" / "sticker-map.json"
    run_public = run_dir / "stickers" / "public"
    if run_map.exists():
        shutil.copy2(run_map, app_map)
    else:
        app_map.write_text("{}\n", encoding="utf-8")
    if run_public.exists():
        for path in run_public.iterdir():
            if path.is_file():
                shutil.copy2(path, public_stickers / path.name)
    state.paths["web_dir"] = str(web)
    mark(run_dir, state, "web_prepared")
    out(f"前端资源已准备: {web}", "green")


def command_web_start(args: argparse.Namespace) -> None:
    web = Path(args.web_dir)
    if not command_exists("npm"):
        out("未找到 npm，请先安装 Node.js。", "red")
        raise SystemExit(1)
    run_command(["npm", "install"], cwd=web)
    run_command(["npm", "run", "build"], cwd=web)
    env = {
        "OLLAMA_URL": args.ollama_url,
        "OLLAMA_MODEL": args.model,
        "OLLAMA_TEMPERATURE": str(args.temperature),
        "OLLAMA_TOP_P": "0.75",
        "OLLAMA_REPEAT_PENALTY": "1.15",
        "MAX_CONSECUTIVE_VISUAL_REPLIES": "1",
        "VISUAL_REPLY_FALLBACK": "呵呵",
        "BANNED_REPLY_PHRASES": args.banned_phrases,
    }
    out(f"启动前端: http://127.0.0.1:{args.port}", "green")
    run_command(["npm", "run", "start", "--", "-H", args.host, "-p", str(args.port)], cwd=web, env=env)


def collect_targets_interactive(path: Path, label: str) -> list[str]:
    out(f"\n请输入{label}，每行一个；空行结束。", "bold")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            break
        values.append(value)
    write_lines(path, values)
    return values


def wizard(args: argparse.Namespace) -> None:
    run_dir, state = ensure_run(args.run, args.resume)
    heading(
        "Me-Distilled 本地向导",
        textwrap.dedent(
            f"""
            本向导会自动准备工具、构建训练数据、本地 LoRA 训练，并用 Ollama 部署。
            所有产物都会放在: {rel(run_dir)}
            请只处理本人或已获得明确授权的聊天记录。
            """
        ).strip(),
    )
    if not prompt_yes("确认继续？", True, auto_yes=args.yes):
        return
    mark(run_dir, state, "authorized")

    command_doctor(args)
    if prompt_yes("是否安装/更新 CLI 依赖？", True, auto_yes=args.yes):
        command_setup_deps(argparse.Namespace(kind="cli"))
    if prompt_yes("是否安装/更新训练依赖？", False, auto_yes=args.yes):
        command_setup_deps(argparse.Namespace(kind="train"))
    mark(run_dir, state, "deps_checked")

    out(
        "\n微信提示：建议使用能被 WeChatMsg 识别的 PC 微信数据。新版/旧版微信数据可能分开存储，切版本后要确认聊天记录已同步。",
        "yellow",
    )
    decrypted_default = str(ROOT / "wechat_decrypted")
    choice = prompt_choice(
        "微信数据库准备情况",
        ["我已经有解密后的数据库目录", "帮我下载并打开 WeChatMsg，我手动解密后继续", "跳过微信步骤，使用已有 contacts/data"],
        1,
        auto_yes=args.yes,
    )
    decrypted = Path(args.decrypted or decrypted_default)
    if choice == 2:
        command_wechat_decrypt(argparse.Namespace(tool="", yes=args.yes))
        out("完成解密后回到这里。", "yellow")
        prompt_text("按回车继续", "", auto_yes=args.yes)
        decrypted = Path(prompt_text("解密目录", decrypted_default, required=True, auto_yes=args.yes))
    elif choice == 1:
        decrypted = Path(prompt_text("解密目录", decrypted_default, required=True, auto_yes=args.yes))

    if choice != 3:
        command_wechat_check(argparse.Namespace(decrypted=str(decrypted)))
        state.paths["decrypted"] = str(decrypted)
        mark(run_dir, state, "db_checked")

    contacts_file = Path(args.contacts) if args.contacts else run_dir / "contacts.txt"
    if contacts_file.exists() and read_lines(contacts_file):
        contacts = read_lines(contacts_file)
        out(f"已读取联系人文件: {contacts_file}", "green")
    else:
        contacts = collect_targets_interactive(contacts_file, "要训练的私聊联系人昵称/备注/wxid")
    if not contacts and choice != 3:
        out("没有联系人，无法继续。", "red")
        raise SystemExit(1)
    state.paths["contacts"] = str(contacts_file)

    if choice != 3:
        matches = match_contacts(decrypted, contacts)
        write_json(run_dir / "contacts.matched.json", matches)
        for item in matches:
            status = "[OK]" if item["status"] == "ok" else "[MISS]"
            out(f"{status} {item['target']} -> {item['name']} / {item['wxid']} / {item['count']} 条")
        if not prompt_yes("联系人匹配结果是否可以继续？", True, auto_yes=args.yes):
            return
        command_wechat_export(argparse.Namespace(run=str(run_dir), resume="", decrypted=str(decrypted), contacts=str(contacts_file), groups=""))

    use_stickers = not args.no_sticker and prompt_yes("是否处理本地表情包资源？", True, auto_yes=args.yes)
    if use_stickers and choice != 3:
        candidates = find_wechat_files()
        default_files = str(candidates[0]) if candidates else ""
        wechat_files = prompt_text("微信 Files 目录", default_files, required=not default_files, auto_yes=args.yes)
        command_sticker_export(argparse.Namespace(run=str(run_dir), resume="", decrypted=str(decrypted), wechat_files=wechat_files))
        command_sticker_map(argparse.Namespace(run=str(run_dir), resume="", decrypted=str(decrypted)))

    mode = args.data_mode or ["text-emoji-tag", "text-emoji", "sticker"][prompt_choice(
        "训练数据类型",
        ["文本 + <emoji:描述> 标签（推荐，前端可映射 emoji）", "文本 + Unicode emoji", "文本 + sticker 标签"],
        1,
        auto_yes=args.yes,
    ) - 1]
    identity_answers = args.identity_answer or []
    command_data_build(
        argparse.Namespace(
            run=str(run_dir),
            resume="",
            decrypted=str(decrypted),
            contacts=str(contacts_file),
            groups="",
            mode=mode,
            no_sticker=not use_stickers,
            synthetic=args.synthetic,
            identity_answer=identity_answers,
        )
    )

    if prompt_yes("是否自动下载/检查训练基座和 GGUF 基座？", True, auto_yes=args.yes):
        command_setup_models(argparse.Namespace(all=True, hf=False, gguf=False, base=args.base, base_gguf=args.base_gguf))
    if not prompt_yes("是否开始本地 LoRA 训练？", False, auto_yes=args.yes):
        out(f"已停在训练前。继续命令: me-distilled train lora --resume {rel(run_dir)}", "cyan")
        return
    command_train_lora(
        argparse.Namespace(
            run=str(run_dir),
            resume="",
            base=args.base,
            data="",
            output="",
            max_length=args.max_length,
            epochs=args.epochs,
            batch_size=1,
            grad_accum=8,
            lr=8e-5,
            rank=16,
            alpha=32,
            dropout=0.05,
            seed=42,
            eval_size=120,
            save_steps=160,
        )
    )
    command_convert_adapter(argparse.Namespace(run=str(run_dir), resume="", base=args.base or "", llama_cpp="", adapter="", out=""))
    model_name = args.ollama_name
    command_ollama_create(argparse.Namespace(run=str(run_dir), resume="", base_gguf=args.base_gguf or "", adapter="", name=model_name))
    command_ollama_test(argparse.Namespace(model=model_name, prompt=[], temperature=0.2))
    if prompt_yes("是否准备并启动本地 Web 聊天前端？", True, auto_yes=args.yes):
        command_web_prepare(argparse.Namespace(run=str(run_dir), resume="", web_dir=str(ROOT / "web-chat")))
        out("前端启动会占用当前终端；需要后台运行可用 pm2 或另开终端。", "yellow")
        command_web_start(
            argparse.Namespace(
                web_dir=str(ROOT / "web-chat"),
                model=model_name,
                host="127.0.0.1",
                port=3000,
                ollama_url="http://127.0.0.1:11434",
                temperature=0.2,
                banned_phrases="",
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="me-distilled", description="本地微信聊天风格模型训练与 Ollama 部署 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="检查 Python/Git/Ollama/GPU/依赖")
    p.set_defaults(func=command_doctor)

    p = sub.add_parser("wizard", help="从微信数据到 Ollama/Web 的一站式向导")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--yes", action="store_true", help="使用默认选项，适合自动化")
    p.add_argument("--decrypted")
    p.add_argument("--contacts")
    p.add_argument("--base")
    p.add_argument("--base-gguf")
    p.add_argument("--ollama-name", default="me-distilled")
    p.add_argument("--data-mode", choices=["text-emoji-tag", "text-emoji", "sticker"])
    p.add_argument("--identity-answer", action="append", default=[])
    p.add_argument("--synthetic", action="store_true", help="启用内置少量构造样本，默认关闭")
    p.add_argument("--no-sticker", action="store_true")
    p.add_argument("--max-length", type=int, default=192)
    p.add_argument("--epochs", type=float, default=2.0)
    p.set_defaults(func=wizard)

    setup = sub.add_parser("setup", help="下载工具、模型或安装依赖")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)
    p = setup_sub.add_parser("deps")
    p.add_argument("--kind", choices=["cli", "train", "all"], default="cli")
    p.set_defaults(func=command_setup_deps)
    p = setup_sub.add_parser("tools")
    p.add_argument("--all", action="store_true")
    p.add_argument("--wechatmsg", action="store_true")
    p.add_argument("--llama-cpp", action="store_true")
    p.set_defaults(func=command_setup_tools)
    p = setup_sub.add_parser("models")
    p.add_argument("--all", action="store_true")
    p.add_argument("--hf", action="store_true")
    p.add_argument("--gguf", action="store_true")
    p.add_argument("--base")
    p.add_argument("--base-gguf")
    p.set_defaults(func=command_setup_models)

    wechat = sub.add_parser("wechat", help="微信数据库解密辅助、检查、导出")
    wechat_sub = wechat.add_subparsers(dest="wechat_command", required=True)
    p = wechat_sub.add_parser("decrypt")
    p.add_argument("--tool", default="")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=command_wechat_decrypt)
    p = wechat_sub.add_parser("check")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.set_defaults(func=command_wechat_check)
    p = wechat_sub.add_parser("match")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.add_argument("--contacts", required=True)
    p.add_argument("--include-groups", action="store_true")
    p.add_argument("--out", default="")
    p.set_defaults(func=command_wechat_match)
    p = wechat_sub.add_parser("export")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.add_argument("--contacts", required=True)
    p.add_argument("--groups", default="")
    p.set_defaults(func=command_wechat_export)

    sticker = sub.add_parser("sticker", help="导出表情包并生成前端映射")
    sticker_sub = sticker.add_subparsers(dest="sticker_command", required=True)
    p = sticker_sub.add_parser("export")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.add_argument("--wechat-files", default="")
    p.set_defaults(func=command_sticker_export)
    p = sticker_sub.add_parser("map")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.set_defaults(func=command_sticker_map)

    data = sub.add_parser("data", help="构建和检查训练数据")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    p = data_sub.add_parser("build")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--decrypted", default=str(ROOT / "wechat_decrypted"))
    p.add_argument("--contacts", required=True)
    p.add_argument("--groups", default="")
    p.add_argument("--mode", choices=["text-emoji-tag", "text-emoji", "sticker"], default="text-emoji-tag")
    p.add_argument("--identity-answer", action="append", default=[])
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--no-sticker", action="store_true")
    p.set_defaults(func=command_data_build)
    p = data_sub.add_parser("report")
    p.add_argument("--data", required=True)
    p.add_argument("--sticker-map", default="")
    p.add_argument("--out", default="")
    p.set_defaults(func=command_data_report)

    train = sub.add_parser("train", help="本地训练")
    train_sub = train.add_subparsers(dest="train_command", required=True)
    p = train_sub.add_parser("lora")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--base", default="")
    p.add_argument("--data", default="")
    p.add_argument("--output", default="")
    p.add_argument("--max-length", type=int, default=192)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lr", type=float, default=8e-5)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-size", type=int, default=120)
    p.add_argument("--save-steps", type=int, default=160)
    p.set_defaults(func=command_train_lora)

    convert = sub.add_parser("convert", help="转换 adapter 为 GGUF")
    convert_sub = convert.add_subparsers(dest="convert_command", required=True)
    p = convert_sub.add_parser("adapter")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--base", default="")
    p.add_argument("--llama-cpp", default="")
    p.add_argument("--adapter", default="")
    p.add_argument("--out", default="")
    p.set_defaults(func=command_convert_adapter)

    ollama = sub.add_parser("ollama", help="创建和测试 Ollama 模型")
    ollama_sub = ollama.add_subparsers(dest="ollama_command", required=True)
    p = ollama_sub.add_parser("create")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--base-gguf", default="")
    p.add_argument("--adapter", default="")
    p.add_argument("--name", default="me-distilled")
    p.set_defaults(func=command_ollama_create)
    p = ollama_sub.add_parser("test")
    p.add_argument("--model", default="me-distilled")
    p.add_argument("--prompt", action="append", default=[])
    p.add_argument("--temperature", type=float, default=0.2)
    p.set_defaults(func=command_ollama_test)

    web = sub.add_parser("web", help="准备和启动 Next.js 聊天前端")
    web_sub = web.add_subparsers(dest="web_command", required=True)
    p = web_sub.add_parser("prepare")
    p.add_argument("--run")
    p.add_argument("--resume")
    p.add_argument("--web-dir", default=str(ROOT / "web-chat"))
    p.set_defaults(func=command_web_prepare)
    p = web_sub.add_parser("start")
    p.add_argument("--web-dir", default=str(ROOT / "web-chat"))
    p.add_argument("--model", default="me-distilled")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=3000)
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--banned-phrases", default="")
    p.set_defaults(func=command_web_start)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
