import type { RunSettings as Settings } from "@/lib/api";

/** Collapsed on every width; the summary line shows the values (Lab 4 lesson). */
export default function RunSettings({
  value,
  maxIterations,
  onChange,
}: {
  value: Settings;
  maxIterations: number;
  onChange: (value: Settings) => void;
}) {
  const summary = [
    `${value.max_iterations} decisions max`,
    value.require_approval ? "approval on" : "approval off",
    value.use_memory ? "memory on" : "memory off",
  ].join(" · ");
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-zinc-700 dark:text-zinc-300">Settings: {summary}</summary>
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-2">
        <label className="flex items-center gap-2">
          Max decisions
          <input
            type="number"
            min={1}
            max={maxIterations}
            value={value.max_iterations}
            onChange={(e) => {
              const n = Math.round(Number(e.target.value));
              if (Number.isFinite(n)) onChange({ ...value, max_iterations: Math.min(maxIterations, Math.max(1, n)) });
            }}
            className="w-16 rounded border border-zinc-300 bg-white px-1 py-0.5 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={value.require_approval}
            onChange={(e) => onChange({ ...value, require_approval: e.target.checked })}
          />
          Require my approval before the final answer
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={value.use_memory}
            onChange={(e) => onChange({ ...value, use_memory: e.target.checked })}
          />
          Use memory of earlier tasks
        </label>
      </div>
    </details>
  );
}
