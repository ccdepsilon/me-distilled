# Me-Distilled

本项目提供一个本地优先的命令行流水线，把已授权的微信聊天记录处理成中文聊天风格训练数据，完成 LoRA 微调、GGUF adapter 转换、Ollama 部署和可选 Web 聊天前端。

## 你需要准备

- Python 3.10+
- Git
- Ollama
- 如需训练 7B LoRA，建议 NVIDIA GPU 和 CUDA 环境
- 已授权的微信聊天记录

CLI 会自动下载开源工具和模型，优先使用国内可用源，失败后切换备用源。微信数据库会优先尝试自动扫描目录、打开微信、读取运行中微信的 key 并解密；如果版本、权限或登录状态不满足要求，再自动打开 WeChatMsg 图形界面作为兜底。

## 安装

```bash
git clone <your-repo-url>
cd Me-Distilled
python -m pip install -e .
me-distilled setup deps --kind cli
```

训练依赖：

```bash
me-distilled setup deps --kind train
```

## 一站式向导

```bash
me-distilled wizard
```

向导会依次完成：

```text
授权确认 -> 环境检查 -> 扫描微信目录 -> 自动打开/提醒打开低版本微信 -> 自动解密或图形兜底
-> 选择联系人 -> 导出聊天 -> 处理表情资源 -> 构建训练数据
-> 下载基座模型 -> LoRA 训练 -> adapter 转 GGUF
-> 创建 Ollama 模型 -> 快速测试 -> 可选启动 Web 前端
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

如果要加入身份问答增强：

```bash
me-distilled wizard \
  --identity-answer "我是某某" \
  --identity-answer "别装，你不知道我是谁？"
```

## 分步命令

检查环境：

```bash
me-distilled doctor
```

下载工具：

```bash
me-distilled setup tools --all
```

下载模型：

```bash
me-distilled setup models --all
```

辅助解密：

```bash
me-distilled wechat scan
me-distilled wechat locate
me-distilled wechat auto-decrypt
me-distilled wechat wdecipher
me-distilled wechat check --decrypted ./wechat_decrypted
```

`wechat scan` 会自动扫描注册表/配置文件中的微信存储位置、默认文档目录下的微信账号目录、`FileStorage/CustomEmotion` 表情目录，以及项目内常见的已解密数据库目录。

`wechat locate` 会在微信已经打开并登录时，优先用 WDecipher/PyWxDump 读取运行中的微信进程信息，打印 `wxid`、微信版本、`filePath` 和目录候选；如果 WDecipher 失败，再切换到 WeChatMsg 备用读取。

`wechat auto-decrypt` 会先提醒用户安装/打开 PC 微信并同步聊天记录，然后优先使用 WDecipher/PyWxDump 读取 `wx_dir/db_key` 并解密数据库；如果 WDecipher 失败，再切换到 WeChatMsg 自动解密，最后才打开 WeChatMsg 图形界面兜底。

`wechat wdecipher` 可以显式使用 WDecipher/PyWxDump 解密方式，适合运行中的微信可通过内存搜索拿到 `db_key` 的情况。

自动解密优先依赖 WDecipher/PyWxDump 的运行中微信读取能力；WeChatMsg 作为备用方案时，支持版本以其自带的 `version_list.json` 为准。旧版微信和新版微信可能使用不同的聊天记录目录，所以换版本后需要在目标版本微信里重新同步聊天记录。

手动兜底：

```bash
me-distilled wechat decrypt
```

联系人匹配和导出：

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

训练、转换和部署：

```bash
me-distilled train lora --run my-run
me-distilled convert adapter --run my-run
me-distilled ollama create --run my-run --name me-distilled
me-distilled ollama test --model me-distilled
```

Web 前端：

```bash
me-distilled web prepare --run my-run
me-distilled web start --model me-distilled --port 3000
```

## 隐私说明

`.gitignore` 默认排除了聊天记录、解密数据库、表情包、模型权重、训练产物和运行目录。不要把私人数据或模型权重提交到公开仓库。
