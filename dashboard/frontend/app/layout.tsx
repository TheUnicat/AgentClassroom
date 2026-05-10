import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TeachingBench",
  description: "RL environment for evaluating LLM teaching quality.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
