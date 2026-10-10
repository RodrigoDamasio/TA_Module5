import type { Sample } from "@/lib/schemas";

/** The stored sample runs: a click replays one (0 LLM calls). */
export default function Suggestions({
  samples,
  disabled,
  onReplay,
}: {
  samples: Sample[];
  disabled: boolean;
  onReplay: (sample: Sample) => void;
}) {
  if (samples.length === 0) return null;
  return (
    <section aria-label="Samples" className="space-y-1">
      <p className="text-xs text-zinc-600 dark:text-zinc-400">Try a stored run (replay, 0 AI calls):</p>
      <ul className="flex flex-wrap gap-2">
        {samples.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onReplay(s)}
              title={s.task}
              className="rounded-full border border-zinc-300 px-3 py-1 text-sm hover:border-orange-700 disabled:opacity-50 dark:border-zinc-700"
            >
              {s.title}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
