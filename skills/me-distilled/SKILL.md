---
name: me-distilled
description: Execute the Me-Distilled local pipeline for authorized WeChat chat-record based Chinese personal dialogue models. Use when the user wants Codex or Claude Code to clone or update the project, prepare dependencies, decrypt or verify local WeChat databases, export selected chats, build training data, train a LoRA adapter, convert it to GGUF, create/test an Ollama model, or prepare the bundled web frontend.
---

# Me-Distilled

This skill is an execution workflow for agents. Do the work yourself with the repository tools; do not merely explain CLI usage unless the user explicitly asks for instructions only.

## Guardrails

- Confirm the user owns the data or has explicit authorization before processing chats.
- Keep decrypted databases, exported chats, sticker assets, model weights, GGUF files, run directories, and credentials local. Never commit or upload them.
- Prefer the repository CLI and scripts over ad hoc rewrites.
- When a step needs user action, pause with the exact action needed, for example "open and log in to PC WeChat, then press Enter".
- Use one run directory per attempt: `runs/<run-name>`. Reuse `--resume` when continuing.

## Operating Loop

1. Inspect the workspace.
   - If the repo is absent, clone `https://github.com/ccdepsilon/me-distilled.git`.
   - If already inside a clone, use it. Do not reclone over local work.
   - Check `git status --short` and avoid touching generated private data.

2. Install and verify the CLI.
   - Assume system-level software should already exist: Python 3.10+, Git, and optionally Node.js/npm for the web frontend.
   - Do not promise automatic installation of Git or Node.js/npm. If missing, stop and ask the user to install them.
   - Ollama can be reused if installed; on Linux the CLI may try to download it, but on Windows tell the user to install official Ollama first.
   - Run `python -m pip install -e .`.
   - Run `me-distilled doctor`.
   - Install CLI dependencies with `me-distilled setup deps --kind cli` if imports or commands fail.

3. Prepare WeChat data.
   - First remind the user to use Windows PC WeChat 3.x, preferably 3.9.x or below.
   - If they downgraded WeChat, tell them to sync from phone before extraction: `我 - 设置 - 聊天记录管理 - 导入与导出 - 导出到电脑 - 选择需要的联系人`.
   - Ask them to keep PC WeChat open and logged in while decrypting.
   - Ask for the target one-to-one contacts if no contacts file exists.
   - Run `me-distilled wechat scan`.
   - Prefer `me-distilled wechat auto-decrypt`; it tries WDecipher first, then WeChatMsg fallback.
   - If the user already has decrypted databases, skip decryption and run `me-distilled wechat check --decrypted <dir>`.
   - If auto-decrypt cannot read the key, ask the user to open/login to Windows PC WeChat 3.x and sync chats, then retry.
   - If all automatic paths fail, open the GUI fallback with `me-distilled wechat decrypt`, let the user finish, then continue from the decrypted directory.

4. Match and export chats.
   - Put selected contacts in a plain text file, one display name/remark/wxid per line.
   - Run `me-distilled wechat match --decrypted <dir> --contacts <contacts.txt>`.
   - Show misses and ask the user to fix names only if matching is not good enough.
   - Run `me-distilled wechat export --run <run> --decrypted <dir> --contacts <contacts.txt>`.

5. Build training data.
   - Default mode is `text-emoji-tag`.
   - If the user wants custom sticker resources or a future sticker selector, run:
     - `me-distilled sticker export --run <run> --decrypted <dir> --wechat-files <WeChat Files>/<wxid>`
     - `me-distilled sticker map --run <run> --decrypted <dir>`
   - Run `me-distilled data build --run <run> --decrypted <dir> --contacts <contacts.txt> --mode text-emoji-tag`.
   - Use `--identity-answer` or `--synthetic` only when the user explicitly asks for synthetic examples.
   - Inspect the data report after building and summarize sample count, sticker/emoji status, and obvious warnings.

6. Train and convert.
   - Install training deps only when training is requested: `me-distilled setup deps --kind train`.
   - Ensure models/tools with `me-distilled setup models --all` and `me-distilled setup tools --all`.
   - If the user wants sticker selection outside the main model, run `me-distilled train sticker-selector --run <run>` after `data build`.
   - Do not assume `me-distilled train lora` trains the sticker selector; it only trains the main chat LoRA.
   - Run `me-distilled train lora --run <run>`.
   - Run `me-distilled convert adapter --run <run>`.
   - If conversion fails, rerun `me-distilled setup tools --llama-cpp` and retry conversion.

7. Create and test Ollama model.
   - Run `me-distilled ollama create --run <run> --name <model-name>`.
   - Run `me-distilled ollama test --model <model-name>`.
   - If quality looks wrong, report likely data/training causes and inspect data reports before retraining.
   - Ask whether to clear intermediate files. If yes, run `me-distilled cleanup --run <run>`.

8. Optional web frontend.
   - Only prepare it when asked: `me-distilled web prepare --run <run>`.
   - For local testing: `me-distilled web start --model <model-name> --port 3000`.
   - For server deployment, verify Ollama is reachable from the frontend through `OLLAMA_URL`.

## Defaults

- Repository: `https://github.com/ccdepsilon/me-distilled.git`
- Run name: use the user's requested name, otherwise a short timestamped name.
- Data mode: `text-emoji-tag`
- Ollama model name: `me-distilled`
- WeChat support expectation: Windows PC WeChat 3.x is recommended; 3.9.12.57 has been verified through WDecipher. Treat WeChat 4.x, Mac WeChat, and mobile databases as unsupported unless the user provides already-decrypted databases.

## Source Priority

Use this order without asking the user to choose mirrors:

- WeChat decrypt: WDecipher first, then WeChatMsg fallback.
- WeChatMsg clone: `gh-proxy.com` -> `ghfast.top` -> `github.com` -> `gitee.com`.
- llama.cpp clone: `gh-proxy.com` -> `ghfast.top` -> `github.com`.
- Base model: ModelScope first, then Hugging Face or hf-mirror direct URL.
- Ollama Linux binary: openEuler mirror -> `ghfast.top` -> gitmirror -> `ollama.com`.

Gitee's Ollama repository is useful as a source mirror, but do not assume it has the official release binary. Prefer downloadable binary archives with a size check.

## Storage Budget

Before training Qwen2.5-7B, warn the user to reserve 35-50 GB. After cleanup, typical retained storage is about 20-28 GB if the HF base is kept, or about 5-6 GB if only the Ollama GGUF base and adapter are retained.

## Completion Report

End with the concrete state, not generic advice:

- repo path and remote URL
- run directory
- decrypted database path used
- contacts file path
- generated training data path and sample count if available
- adapter/GGUF paths if created
- Ollama model name and test result
- any step that still requires user action
