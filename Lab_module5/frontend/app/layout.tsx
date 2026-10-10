import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import PrivacyNotice from "@/components/PrivacyNotice";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Research Assistant — Multi-Agent",
  description:
    "A Supervisor agent coordinates Researcher, Writer, Reviewer and Fact-Checker agents to answer a research question with cited Wikipedia sources.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <div className="mx-auto flex max-w-7xl flex-wrap items-baseline justify-between gap-2 px-4 py-3">
            <h1 className="text-lg font-semibold">Research Assistant</h1>
            <p className="text-xs text-zinc-600 dark:text-zinc-400">
              Supervisor · Researcher · Writer · Reviewer · Fact-Checker
            </p>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-4">{children}</main>
        <footer className="mx-auto w-full max-w-7xl px-4 pb-6">
          <PrivacyNotice />
        </footer>
      </body>
    </html>
  );
}
