"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import stickerMap from "./sticker-map.json";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type RenderPart =
  | { type: "text"; value: string }
  | { type: "sticker"; value: string }
  | { type: "emoji"; value: string; label: string };

const stickers: Record<string, string> = stickerMap;

const wechatEmojiMap: Record<string, string> = {
  微笑: "🙂",
  撇嘴: "😒",
  色: "😍",
  发呆: "😳",
  得意: "😎",
  流泪: "😢",
  害羞: "☺️",
  闭嘴: "🤐",
  睡: "😴",
  大哭: "😭",
  尴尬: "😅",
  发怒: "😡",
  调皮: "😜",
  呲牙: "😁",
  惊讶: "😮",
  难过: "😔",
  酷: "😎",
  冷汗: "😰",
  抓狂: "😫",
  吐: "🤮",
  偷笑: "🤭",
  愉快: "😄",
  白眼: "🙄",
  傲慢: "😤",
  饥饿: "🤤",
  困: "😪",
  惊恐: "😨",
  流汗: "😓",
  憨笑: "😄",
  悠闲: "😌",
  奋斗: "💪",
  咒骂: "😠",
  疑问: "🤔",
  嘘: "🤫",
  晕: "😵",
  衰: "😞",
  骷髅: "💀",
  敲打: "🔨",
  再见: "👋",
  擦汗: "😅",
  抠鼻: "🤭",
  鼓掌: "👏",
  坏笑: "😏",
  哈欠: "🥱",
  亲亲: "😘",
  可爱: "🥰",
  菜刀: "🔪",
  西瓜: "🍉",
  啤酒: "🍺",
  咖啡: "☕",
  饭: "🍚",
  猪头: "🐷",
  玫瑰: "🌹",
  凋谢: "🥀",
  嘴唇: "💋",
  爱心: "❤️",
  心碎: "💔",
  蛋糕: "🎂",
  炸弹: "💣",
  便便: "💩",
  月亮: "🌙",
  太阳: "☀️",
  拥抱: "🫂",
  强: "👍",
  弱: "👎",
  握手: "🤝",
  胜利: "✌️",
  抱拳: "🙏",
  勾引: "☝️",
  拳头: "✊",
  OK: "👌",
  跳跳: "💃",
  发抖: "😖",
  怄火: "😡",
  转圈: "😵‍💫",
  无语: "😑",
  捂脸: "🤦",
  委屈: "🥺",
  融化: "🫠",
  笑: "😄",
  笑哭: "😂",
  笑死: "😂",
  喜欢: "😍",
  叹气: "😮‍💨",
  生气: "😡",
  苦笑: "😅",
  拜托: "🙏",
  看看: "👀",
  吃瓜: "🍉",
  狗头: "🙂",
  加油: "💪"
};

function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function splitMessage(content: string) {
  return content
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseLine(line: string): RenderPart[] {
  const parts: RenderPart[] = [];
  const pattern = /<sticker:([^>]+)>|<emoji:([^>]+)>|\[([^\[\]]{1,12})\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(line))) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: line.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      const stickerName = match[1].trim();
      if (stickers[stickerName]) {
        parts.push({ type: "sticker", value: stickerName });
      }
    } else if (match[2] && wechatEmojiMap[match[2].trim()]) {
      const emojiName = match[2].trim();
      parts.push({ type: "emoji", label: emojiName, value: wechatEmojiMap[emojiName] });
    } else if (match[3] && wechatEmojiMap[match[3]]) {
      parts.push({ type: "emoji", label: match[3], value: wechatEmojiMap[match[3]] });
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < line.length) {
    parts.push({ type: "text", value: line.slice(lastIndex) });
  }

  return parts.filter((part) => part.type !== "text" || part.value.trim().length > 0);
}

function renderPart(part: RenderPart, index: number): ReactNode {
  if (part.type === "text") {
    return <span key={index}>{part.value}</span>;
  }

  if (part.type === "emoji") {
    return (
      <span aria-label={part.label} className="emoji" key={index} title={part.label}>
        {part.value}
      </span>
    );
  }

  return (
    <img
      alt={part.value}
      className="sticker"
      key={index}
      src={stickers[part.value]}
      title={part.value}
    />
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const parsedLines = splitMessage(message.content)
    .map((line) => parseLine(line))
    .filter((parts) => parts.length > 0);

  if (parsedLines.length === 0) {
    return null;
  }

  return (
    <div className={`message-group ${message.role}`}>
      {parsedLines.map((parts, index) => {
        const isStickerOnly = parts.length === 1 && parts[0].type === "sticker";
        return (
          <article
            className={`bubble ${message.role}${isStickerOnly ? " sticker-only" : ""}`}
            key={`${message.id}-${index}`}
          >
            {parts.map(renderPart)}
          </article>
        );
      })}
    </div>
  );
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: createId(),
      role: "assistant",
      content: "你好呀"
    }
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const canSend = useMemo(() => input.trim().length > 0 && !isLoading, [input, isLoading]);

  useEffect(() => {
    const scrollToBottom = () => {
      if (messagesRef.current) {
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
      }
      messagesEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    };

    scrollToBottom();
    const frame = requestAnimationFrame(scrollToBottom);
    const timer = window.setTimeout(scrollToBottom, 120);

    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [messages, isLoading]);

  async function sendMessage(event: FormEvent) {
    event.preventDefault();

    const text = input.trim();
    if (!text || isLoading) return;

    const nextMessages: ChatMessage[] = [
      ...messages,
      {
        id: createId(),
        role: "user",
        content: text
      }
    ];

    setMessages(nextMessages);
    setInput("");
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: nextMessages.map(({ role, content }) => ({ role, content }))
        })
      });

      const data = (await response.json()) as { reply?: string; error?: string };
      if (!response.ok) {
        throw new Error(data.error || "请求失败");
      }

      setMessages((current) => [
        ...current,
        {
          id: createId(),
          role: "assistant",
          content: data.reply || "嗯"
        }
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
      setInput(text);
    } finally {
      setIsLoading(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }

  return (
    <main className="shell">
      <section className="chat" aria-label="chat">
        <header className="topbar">
          <div className="avatar">我</div>
          <div>
            <h1>微信聊天</h1>
            <p>在线</p>
          </div>
        </header>

        <div className="messages" ref={messagesRef}>
          {messages.map((message) => (
            <Bubble key={message.id} message={message} />
          ))}
          {isLoading ? (
            <div className="message-group assistant">
              <article className="bubble assistant typing">
                <span />
                <span />
                <span />
              </article>
            </div>
          ) : null}
          <div ref={messagesEndRef} />
        </div>

        {error ? <div className="error">{error}</div> : null}

        <form className="composer" onSubmit={sendMessage}>
          <textarea
            ref={inputRef}
            value={input}
            placeholder="发消息"
            rows={1}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button type="submit" disabled={!canSend}>
            发送
          </button>
        </form>
      </section>
    </main>
  );
}
