# Me-Distilled

Me-Distilled 是一个本地优先的命令行工具，用于把已授权的微信聊天记录处理成中文聊天风格训练数据，并完成 LoRA 微调、GGUF adapter 转换和 Ollama 本地部署。转换后的模型可以在本地无 GPU 推理；训练 LoRA 通常需要 NVIDIA GPU 和 CUDA 环境。

本项目适合个人研究、学习和本地实验。请只处理你本人拥有或已获得明确授权的数据。

## 功能

- 扫描本机微信数据目录和已解密数据库目录。
- 优先使用 WDecipher 自动解密微信数据库，失败后使用 WeChatMsg 兜底。
- 按联系人导出一对一聊天记录。
- 构建适合聊天风格微调的监督训练数据。
- 支持文本、emoji 标签、Unicode emoji 和实验性的 sticker 标签数据模式。
- 本地训练 LoRA adapter。
- 将 adapter 转为 GGUF，并创建 Ollama 模型。
- 可选准备一个本地 Web 聊天前端。

## 主要开源组件

本项目是一个本地流水线封装，核心能力来自以下开源项目和生态：

- WDecipher：读取运行中的 Windows PC 微信信息并解密本地 SQLite 数据库。
- WeChatMsg：作为微信数据库解密和导出流程的备用工具。
- llama.cpp：将 LoRA adapter 转换为 GGUF。
- Ollama：本地模型创建和推理。
- Qwen2.5-7B-Instruct：默认训练基座模型。
- ModelScope / Hugging Face Hub：模型下载来源。
- PyTorch / Transformers / PEFT / Accelerate：LoRA 训练。
- Next.js / React：可选 Web 聊天前端。

具体许可证和使用限制请以各上游项目为准。

## 环境要求

- Windows：推荐用于微信数据库解密。
- Python 3.10+
- Git
- Ollama
- 本地推理可无 GPU 运行；如需本地训练 7B LoRA，建议准备 NVIDIA GPU 和 CUDA 环境。
- 已授权的微信聊天记录。

## 安装

```bash
git clone https://github.com/ccdepsilon/me-distilled.git
cd me-distilled
python -m pip install -e .
me-distilled setup deps --kind cli
```

准备训练环境时再安装训练依赖：

```bash
me-distilled setup deps --kind train
```

## 快速开始

运行交互式向导：

```bash
me-distilled wizard
```

向导会依次完成：

```text
授权确认
-> 环境检查
-> 微信目录扫描
-> 数据库解密/检查
-> 选择联系人
-> 导出聊天记录
-> 可选处理 emoji/sticker 资源
-> 构建训练数据
-> 下载/检查模型
-> LoRA 训练
-> GGUF adapter 转换
-> 创建 Ollama 模型
-> 快速测试
```

常用参数：

```bash
me-distilled wizard --run my-run
me-distilled wizard --resume runs/my-run
me-distilled wizard --decrypted ./wechat_decrypted
me-distilled wizard --contacts ./contacts.txt
me-distilled wizard --no-sticker
me-distilled wizard --data-mode text-emoji-tag
```

如果需要加入少量身份问答样本：

```bash
me-distilled wizard \
  --identity-answer "我是某某" \
  --identity-answer "另一个回答"
```

## 数据模式

向导会让你选择训练数据中的表情表示方式：

- `text-emoji-tag`：推荐。把 emoji 写成语义标签，例如 `<emoji:微笑>`，后续前端可以稳定映射成 Unicode emoji 或图片。
- `text-emoji`：直接把 Unicode emoji 写入训练文本。
- `sticker`：实验性。把自定义表情包写成 `<sticker:描述>` 标签并放入主聊天模型训练数据。

大多数情况下推荐使用 `text-emoji-tag`。自定义表情包更适合通过单独的 selector 或前端规则控制，不一定要直接放进主聊天模型。

## 常用命令

检查环境：

```bash
me-distilled doctor
```

安装依赖、下载工具和模型：

```bash
me-distilled setup deps --kind cli
me-distilled setup deps --kind train
me-distilled setup tools --all
me-distilled setup models --all
```

微信数据库相关：

```bash
me-distilled wechat scan
me-distilled wechat locate
me-distilled wechat auto-decrypt
me-distilled wechat check --decrypted ./wechat_decrypted
```

`wechat auto-decrypt` 会优先通过 WDecipher 读取运行中的微信进程并解密数据库；失败后会尝试 WeChatMsg 自动解密，再失败则打开 WeChatMsg 图形界面兜底。

### 微信版本支持

自动解密主要面向 Windows PC 微信 3.x。实际能否自动解密取决于当前微信版本、登录状态、进程权限，以及工具是否能从运行中的微信进程读取到有效的 64 位 `db_key`。

当前建议：

- 推荐：Windows PC 微信 3.x，先打开并登录微信，确认聊天记录已经同步。
- 已验证：3.9.12.57 可通过 WDecipher 路径读取并解密。
- 常见可用范围：3.2.x 到 3.9.x 的 PC 微信版本更可能成功。
- 不推荐：微信 4.x、新版大改版客户端、Mac 微信、移动端微信数据库。

WeChatMsg 兜底路径的支持范围以其上游工具自带版本表为准；本工具会在运行时尽量打印可读取到的版本信息。若自动解密失败，可以手动准备已解密数据库目录后继续执行后续数据构建和训练步骤。

联系人匹配和聊天导出：

```bash
me-distilled wechat match --decrypted ./wechat_decrypted --contacts ./contacts.txt
me-distilled wechat export --run my-run --decrypted ./wechat_decrypted --contacts ./contacts.txt
```

构建训练数据：

```bash
me-distilled data build \
  --run my-run \
  --decrypted ./wechat_decrypted \
  --contacts ./contacts.txt \
  --mode text-emoji-tag
```

训练、转换和 Ollama 部署：

```bash
me-distilled train lora --run my-run
me-distilled convert adapter --run my-run
me-distilled ollama create --run my-run --name me-distilled
me-distilled ollama test --model me-distilled
```

可选本地 Web 前端：

```bash
me-distilled web prepare --run my-run
me-distilled web start --model me-distilled --port 3000
```

## Agent Skill

仓库内提供了 `skills/me-distilled`，可供 Codex 或 Claude Code 这类代码代理使用。这个 skill 不是普通的命令说明，而是让代理按照本项目同样的流水线主动执行：克隆/更新仓库、安装依赖、检查微信数据、构建数据、训练、转换、创建 Ollama 模型并测试。

使用时可以把该目录安装到对应工具的 skills 目录，然后对代理说：

```text
Use $me-distilled to process my authorized local WeChat data and train/deploy the model.
```

## 隐私说明

`.gitignore` 默认排除了聊天记录、解密数据库、表情资源、模型权重和训练产物。不要把私人聊天记录、解密数据库、表情文件或模型权重提交到公开仓库。

## 免责声明

本项目仅用于本地研究和学习。请遵守平台规则、当地法律法规，并尊重聊天对象的隐私。
