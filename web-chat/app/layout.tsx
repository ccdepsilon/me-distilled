import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "微信聊天",
  description: "A small chat UI for a local Ollama model"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
