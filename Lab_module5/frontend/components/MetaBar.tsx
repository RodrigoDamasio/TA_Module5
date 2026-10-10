import { formatCost, formatMs } from "@/lib/format";
import type { RunView } from "@/lib/schemas";

/** What the run cost and who made it (course §2.3 cost management, §2.10 accountability). */
export default function MetaBar({ run }: { run: RunView }) {
  const m = run.meta;
  const models = [...new Set(Object.values(m.models).filter(Boolean))].join(", ") || "—";
  const parts = [
    m.generated_by,
    `model ${models}`,
    `prompt v${m.prompt_version || "?"}`,
    `${m.llm_calls} AI call${m.llm_calls === 1 ? "" : "s"}${m.cached_calls ? ` + ${m.cached_calls} cached` : ""}`,
    `${(m.tokens.input + m.tokens.output).toLocaleString("en-US")} tokens`,
    `est. ${formatCost(m.est_cost_usd)} at paid prices`,
  ];
  if (m.duration_ms !== null) parts.push(formatMs(m.duration_ms));
  return <p className="text-xs text-zinc-600 dark:text-zinc-400">{parts.join(" · ")}</p>;
}
