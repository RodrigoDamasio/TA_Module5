"use client";
import { useEffect, useRef } from "react";
import type { Board } from "@/lib/agents";

const MAX_LINES = 60;

/** Every step as one line, newest last. A scroll region (keyboard-focusable). */
export default function ActivityFeed({ board }: { board: Board }) {
  const lines = board.feed.slice(-MAX_LINES);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // follow the newest line (the user can still scroll back)
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length]);
  return (
    <section aria-labelledby="feed-title" className="space-y-2">
      <h2 id="feed-title" className="text-sm font-semibold tracking-wide uppercase">
        Activity
      </h2>
      {lines.length === 0 ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">No activity yet.</p>
      ) : (
        <div ref={box} role="region" aria-label="Activity feed" tabIndex={0} className="max-h-64 overflow-y-auto rounded-md border border-zinc-200 p-2 dark:border-zinc-800">
          <ol className="space-y-1 text-sm">
            {lines.map((l) => (
              <li key={l.id} data-agent={l.agent}>
                {l.text}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
