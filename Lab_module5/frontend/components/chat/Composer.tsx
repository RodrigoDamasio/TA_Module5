"use client";
import { forwardRef } from "react";

interface Props {
  value: string;
  maxChars: number;
  disabledReason: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  children?: React.ReactNode; // run settings, under the box
}

/** From Lab 4: Enter sends, Shift+Enter adds a line; the disabled reason is visible text. */
const Composer = forwardRef<HTMLTextAreaElement, Props>(function Composer(p, ref) {
  const disabled = p.disabledReason !== null;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) p.onSubmit();
      }}
      className="sticky bottom-0 space-y-2 border-t border-zinc-200 bg-[var(--background)] pt-3 pb-2 dark:border-zinc-800"
    >
      <label htmlFor="task" className="sr-only">
        Research task
      </label>
      <textarea
        id="task"
        ref={ref}
        rows={2}
        value={p.value}
        maxLength={p.maxChars}
        onChange={(e) => p.onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!disabled) p.onSubmit();
          }
        }}
        placeholder="Ask a research question, e.g. When should I use RAG instead of fine-tuning?"
        className="w-full resize-y rounded-md border border-zinc-300 bg-white p-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        aria-describedby="composer-hint"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={disabled}
          aria-busy={p.busy}
          className="rounded-md bg-orange-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-800 disabled:bg-zinc-500 dark:disabled:bg-zinc-700"
        >
          Send
        </button>
        <span id="composer-hint" className="text-xs text-zinc-600 dark:text-zinc-400">
          {p.disabledReason ?? "Enter to send, Shift+Enter for a new line."} {p.value.length}/{p.maxChars}
        </span>
      </div>
      {p.children}
    </form>
  );
});

export default Composer;
