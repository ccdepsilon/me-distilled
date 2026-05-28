# Me-Distilled

Me-Distilled 是一个本地优先的命令行工具，用于把已授权的微信聊天记录处理成中文聊天风格训练数据，并完成 LoRA 微调、GGUF adapter 转换和 Ollama 本地部署。

本项目适合个人研究、学习和本地实验。请只处理你本人拥有或已获得明确授权的数据。

## 功能

- 扫描本机微信数据目录和已解密数据库目录。
- 优先使用 WDecipher/PyWxDump 自动解密微信数据库，失败后使用 WeChatMsg 兜底。
- 按联系人导出一对一聊天记录。
- 构建适合聊天风格微调的监督训练数据。
- 支持文本、emoji 标签、Unicode emoji 和实验性的 sticker 标签数据模式。
- 本地训练 LoRA adapter。
- 将 adapter 转为 GGUF，并创建 Ollama 模型。
- 可选准备一个本地 Web 聊天前端。

## 环境要求

- Windows：推荐用于微信数据库解密。
- Python 3.10+
- Git
- Ollama
- 如需本地训练 7B LoRA，建议准备 NVIDIA GPU 和 CUDA 环境。
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

`wechat auto-decrypt` 会优先通过 WDecipher/PyWxDump 读取运行中的微信进程并解密数据库；失败后会尝试 WeChatMsg 自动解密，再失败则打开 WeChatMsg 图形界面兜底。

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

## 隐私说明

`.gitignore` 默认排除了聊天记录、解密数据库、表情资源、模型权重和训练产物。不要把私人聊天记录、解密数据库、表情文件或模型权重提交到公开仓库。

## 免责声明

本项目仅用于本地研究和学习。请遵守平台规则、当地法律法规，并尊重聊天对象的隐私。
