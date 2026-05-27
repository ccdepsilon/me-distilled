# Me Distilled Web Chat

Next.js 聊天前端。浏览器只访问本服务的 `/api/chat`，后端再转发到本机 Ollama，避免直接暴露 Ollama API。

## 功能

- 无密码，打开网页即可聊天。
- 自动维护最近上下文，最后一条必须是用户消息。
- 模型多行回复会拆成多个微信气泡。
- `<sticker:描述>` 只在 `app/sticker-map.json` 能匹配到本地 gif/png/jpg 时显示；匹配不到会被过滤。
- 微信内置 `[微笑]`、`[发呆]`，以及模型输出的 `<emoji:微笑>`、`<emoji:流泪>` 等会映射成 Unicode emoji。
- 如果没有独立 sticker selector，后端会以 `AUTO_STICKER_CHANCE` 的概率按用户输入和模型回复匹配 sticker 描述并追加。
- 默认最多允许连续 1 次纯 emoji / 纯 sticker 回复；如果模型继续只发表情，会替换成“呵呵”。
- 默认过滤包含“叫你”的模型回复，并自动重生成；多次失败后返回“呵呵”。

## 环境变量

```bash
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=me-distilled-text-emoji
AUTO_STICKER_CHANCE=0.3
OLLAMA_TEMPERATURE=0.2
OLLAMA_TOP_P=0.75
OLLAMA_REPEAT_PENALTY=1.15
MAX_CONSECUTIVE_VISUAL_REPLIES=1
VISUAL_REPLY_FALLBACK=呵呵
MAX_REPLY_REGEN_ATTEMPTS=2
BANNED_REPLY_PHRASES=叫你
STICKER_SELECTOR_URL=
```

如果后面单独启动 sticker selector HTTP 服务，设置 `STICKER_SELECTOR_URL`。接口约定：

```json
{"messages":[{"role":"user","content":"你在干嘛"}],"reply":"我在坐着"}
```

返回：

```json
{"sticker":"在玩洛克王国"}
```

或者：

```json
{"selected":"__none__"}
```

## 运行

```bash
npm install
npm run build

OLLAMA_URL=http://127.0.0.1:11434 \
OLLAMA_MODEL=me-distilled-text-emoji \
AUTO_STICKER_CHANCE=0.3 \
OLLAMA_TEMPERATURE=0.2 \
VISUAL_REPLY_FALLBACK=呵呵 \
BANNED_REPLY_PHRASES=叫你 \
npm run start -- -H 0.0.0.0 -p 3000
```

pm2：

```bash
pm2 delete me-distilled-web 2>/dev/null || true

OLLAMA_URL=http://127.0.0.1:11434 \
OLLAMA_MODEL=me-distilled-text-emoji \
AUTO_STICKER_CHANCE=0.3 \
OLLAMA_TEMPERATURE=0.2 \
VISUAL_REPLY_FALLBACK=呵呵 \
BANNED_REPLY_PHRASES=叫你 \
pm2 start npm --name me-distilled-web -- start -- -H 0.0.0.0 -p 3000

pm2 save
```
