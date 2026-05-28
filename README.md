# Me-Distilled

Me-Distilled is a local-first CLI pipeline for building a personal Chinese chat-style model from authorized WeChat chat records. It helps you decrypt and export local WeChat data, build training datasets, fine-tune a LoRA adapter, convert the adapter to GGUF, and create an Ollama model for local inference.

The project is designed for personal research and experimentation. Only process data that you own or have explicit permission to use.

## Features

- Scan local WeChat data directories and decrypted database folders.
- Prefer WDecipher/PyWxDump for automatic WeChat database decryption, with WeChatMsg as a fallback.
- Export selected one-to-one conversations from decrypted WeChat databases.
- Build chat-style supervised fine-tuning data with text and optional emoji/sticker handling.
- Train a Qwen-style LoRA adapter locally.
- Convert the adapter to GGUF and create an Ollama model.
- Optionally prepare a small local web chat frontend.

## Requirements

- Windows is recommended for WeChat decryption.
- Python 3.10+
- Git
- Ollama
- NVIDIA GPU + CUDA environment if you plan to train a 7B LoRA locally
- Authorized WeChat chat records

## Install

```bash
git clone https://github.com/ccdepsilon/me-distilled.git
cd me-distilled
python -m pip install -e .
me-distilled setup deps --kind cli
```

Install training dependencies only when you are ready to train:

```bash
me-distilled setup deps --kind train
```

## Quick Start

Run the interactive wizard:

```bash
me-distilled wizard
```

The wizard will guide you through:

```text
authorization check
-> environment check
-> WeChat directory scan
-> database decrypt/check
-> contact selection
-> chat export
-> optional emoji/sticker resource processing
-> dataset build
-> model download/check
-> LoRA training
-> GGUF adapter conversion
-> Ollama model creation
-> quick test
```

Common options:

```bash
me-distilled wizard --run my-run
me-distilled wizard --resume runs/my-run
me-distilled wizard --decrypted ./wechat_decrypted
me-distilled wizard --contacts ./contacts.txt
me-distilled wizard --no-sticker
me-distilled wizard --data-mode text-emoji-tag
```

If you want to add a small number of identity Q&A examples:

```bash
me-distilled wizard \
  --identity-answer "I am <your answer>" \
  --identity-answer "<another answer>"
```

## Data Modes

The wizard currently offers three data modes:

- `text-emoji-tag`: recommended. Training data keeps emoji as semantic tags, for example `<emoji:smile>`. A frontend can later map the tag to a Unicode emoji or image.
- `text-emoji`: stores Unicode emoji directly in the training text.
- `sticker`: experimental. Stores custom sticker tags such as `<sticker:desc>` directly in the main chat model data.

For most users, `text-emoji-tag` is the safest default. Custom sticker sending is easier to control outside the main chat model with a separate selector or frontend rule.

## Useful Commands

Check the environment:

```bash
me-distilled doctor
```

Install tools and dependencies:

```bash
me-distilled setup deps --kind cli
me-distilled setup deps --kind train
me-distilled setup tools --all
me-distilled setup models --all
```

Work with WeChat databases:

```bash
me-distilled wechat scan
me-distilled wechat locate
me-distilled wechat auto-decrypt
me-distilled wechat check --decrypted ./wechat_decrypted
```

`wechat auto-decrypt` first tries WDecipher/PyWxDump against the running WeChat process. If that fails, it tries WeChatMsg automatic decryption, then falls back to opening the WeChatMsg GUI.

Match contacts and export chats:

```bash
me-distilled wechat match --decrypted ./wechat_decrypted --contacts ./contacts.txt
me-distilled wechat export --run my-run --decrypted ./wechat_decrypted --contacts ./contacts.txt
```

Build training data:

```bash
me-distilled data build \
  --run my-run \
  --decrypted ./wechat_decrypted \
  --contacts ./contacts.txt \
  --mode text-emoji-tag
```

Train, convert, and deploy with Ollama:

```bash
me-distilled train lora --run my-run
me-distilled convert adapter --run my-run
me-distilled ollama create --run my-run --name me-distilled
me-distilled ollama test --model me-distilled
```

Optional local web frontend:

```bash
me-distilled web prepare --run my-run
me-distilled web start --model me-distilled --port 3000
```

## Privacy

Generated chat exports, decrypted databases, sticker assets, model weights, and run artifacts are ignored by Git by default. Do not commit private chat data, decrypted databases, sticker files, or model weights to a public repository.

## Disclaimer

This project is for local research and learning. Respect platform terms, local laws, and the privacy of other people in your conversations.
