---
name: me-distilled-local-pipeline
description: Build and operate a local Me-Distilled pipeline for WeChat chat-record based Chinese personal dialogue models. Use when the user asks Codex or Claude Code to clone the required repositories, prepare WeChatMsg/llama.cpp/model dependencies, process authorized local WeChat data, train a local LoRA adapter, convert it to GGUF, create an Ollama model, test it, or deploy the bundled web chat frontend.
---

# Me-Distilled Local Pipeline

Use this skill to drive the repository's `me-distilled` CLI end to end. Prefer the CLI over rewriting ad hoc scripts.

## Guardrails

- Confirm the user is processing only their own data or data with explicit authorization.
- Never commit or upload decrypted WeChat databases, exported chats, stickers, model weights, GGUF files, run directories, or credentials.
- Keep all generated artifacts under `runs/<run-name>/`, `.cache/me-distilled/`, `model/`, or `base_models/`.
- If publishing to GitHub, publish code only. Verify `.gitignore` excludes private data and large artifacts.

## Fast Path

When the user wants the simplest local path, run:

```bash
python -m pip install -e .
me-distilled setup deps --kind cli
me-distilled doctor
me-distilled wizard
```

If the user already has decrypted databases and a contact list:

```bash
me-distilled wizard \
  --decrypted ./wechat_decrypted \
  --contacts ./contacts.txt \
  --data-mode text-emoji-tag
```

For unattended defaults, add `--yes`, but do this only when paths are already known.

## Repository And Tools

If the project repo is absent, clone it first:

```bash
git clone <repo-url> Me-Distilled
cd Me-Distilled
python -m pip install -e .
```

Then let the CLI download third-party tools and models:

```bash
me-distilled setup tools --all
me-distilled setup models --all
```

The CLI tries primary sources first and then fallback mirrors. If both fail, ask the user for a local path and pass it with `--tool`, `--base`, `--base-gguf`, or `--llama-cpp`.

## Stepwise Workflow

Use stepwise commands when debugging, resuming, or explaining each phase.

1. Check environment:

```bash
me-distilled doctor
```

2. Prepare or check WeChat databases:

```bash
me-distilled wechat decrypt
me-distilled wechat check --decrypted ./wechat_decrypted
```

3. Match contacts and export chats:

```bash
me-distilled wechat match --decrypted ./wechat_decrypted --contacts ./contacts.txt
me-distilled wechat export --run my-run --decrypted ./wechat_decrypted --contacts ./contacts.txt
```

4. Optionally process stickers:

```bash
me-distilled sticker export --run my-run --decrypted ./wechat_decrypted --wechat-files "<WeChat Files>/<wxid>"
me-distilled sticker map --run my-run --decrypted ./wechat_decrypted
```

5. Build data:

```bash
me-distilled data build \
  --run my-run \
  --decrypted ./wechat_decrypted \
  --contacts ./contacts.txt \
  --mode text-emoji-tag
```

Add identity answers only when the user explicitly asks:

```bash
me-distilled data build \
  --run my-run \
  --decrypted ./wechat_decrypted \
  --contacts ./contacts.txt \
  --mode text-emoji-tag \
  --identity-answer "我是某某" \
  --identity-answer "别装，你不知道我是谁？"
```

6. Train, convert, and deploy:

```bash
me-distilled train lora --run my-run
me-distilled convert adapter --run my-run
me-distilled ollama create --run my-run --name me-distilled
me-distilled ollama test --model me-distilled
```

7. Prepare/start web frontend:

```bash
me-distilled web prepare --run my-run
me-distilled web start --model me-distilled --port 3000
```

## Failure Handling

- If WeChatMsg cannot decrypt automatically, open it with `me-distilled wechat decrypt`, let the user complete the GUI step, then resume with `me-distilled wizard --resume runs/<run>`.
- If ModelScope fails, the CLI falls back to Hugging Face. If both fail, ask for local `--base` and `--base-gguf`.
- If `llama.cpp` conversion fails, rerun `me-distilled setup tools --llama-cpp`, then `me-distilled convert adapter --run <run>`.
- If Ollama cannot create the model, verify the base GGUF and adapter GGUF paths in `runs/<run>/status.json`.
- If the frontend API returns empty/non-JSON responses, inspect `pm2 logs` or the Next.js terminal and verify Ollama is reachable at `OLLAMA_URL`.
