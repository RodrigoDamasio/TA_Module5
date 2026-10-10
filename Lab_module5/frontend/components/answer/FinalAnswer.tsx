"use client";
import { useState } from "react";
import Badge from "@/components/Badge";
import { domain, flagLabel } from "@/lib/format";
import type { RunView } from "@/lib/schemas";
import Markdown, { sourceAnchor } from "./Markdown";

const WARN_FLAGS = new Set(["forced", "degraded", "unsourced", "truncated", "canary_leak"]);

/** The answer without the model's own "Sources" section (we render a linked list). */
export function stripSources(markdown: string): string {
  return markdown.split(/\n#{1,6}\s*sources\s*\n|\n\*\*sources\*\*\s*\n/i)[0].trimEnd();
}

export function SourceList({ run }: { run: RunView }) {
  if (run.sources.length === 0) return null;
  return (
    <section aria-label="Sources" className="mt-4 border-t border-zinc-200 pt-3 dark:border-zinc-800">
      <h3 className="text-sm font-semibold">Sources</h3>
      <ol className="mt-1 space-y-1 text-sm">
        {run.sources.map((s) => (
          <li key={s.n} id={sourceAnchor(run.run_id, s.n)} className="scroll-mt-20">
            <span className="font-mono text-xs">[{s.n}]</span>{" "}
            <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="text-orange-800 underline dark:text-orange-300">
              {s.title}
            </a>{" "}
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{domain(s.url)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function Flags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null;
  return (
    <ul aria-label="Flags" className="flex flex-wrap gap-1.5">
      {flags.map((f) => (
        <li key={f}>
          <Badge tone={WARN_FLAGS.has(f) ? "warn" : "neutral"}>{flagLabel(f)}</Badge>
        </li>
      ))}
    </ul>
  );
}

export default function FinalAnswer({ run }: { run: RunView }) {
  const [copied, setCopied] = useState(false);
  const text = run.final_output ?? "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${run.run_id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <article aria-label="Final answer" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">AI-generated</Badge>
        <Flags flags={run.flags} />
      </div>
      <Markdown text={stripSources(text)} sources={run.sources} runId={run.run_id} />
      <SourceList run={run} />
      <div className="flex flex-wrap gap-3 text-sm">
        <button type="button" onClick={copy} className="font-medium text-orange-800 underline dark:text-orange-300">
          {copied ? "Copied" : "Copy answer"}
        </button>
        <button type="button" onClick={download} className="font-medium text-orange-800 underline dark:text-orange-300">
          Download .md
        </button>
      </div>
    </article>
  );
}
