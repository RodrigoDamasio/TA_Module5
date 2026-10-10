import Badge from "@/components/Badge";
import Markdown from "@/components/answer/Markdown";
import { agentTitle } from "@/lib/agents";
import { formatMs } from "@/lib/format";
import type { Entry, RunView } from "@/lib/schemas";
import { FactCheckTable, ReviewView } from "./WorkerData";

function Cost({ entry }: { entry: Entry }) {
  if (entry.llm_calls === 0 && entry.cached_calls === 0) return null;
  const how = entry.cached ? "cached" : `${entry.llm_calls} call${entry.llm_calls === 1 ? "" : "s"}`;
  return (
    <span className="text-xs text-zinc-600 dark:text-zinc-400">
      {how} · {formatMs(entry.duration_ms)}
    </span>
  );
}

function DecisionEntry({ entry, limit }: { entry: Entry; limit: number }) {
  const d = entry.decision!;
  return (
    <div className="space-y-1">
      <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <span>Supervisor · {d.forced ? "forced decision" : `decision ${entry.iteration} of ${limit}`}</span>
        {d.repaired && <Badge tone="warn">reply repaired</Badge>}
        {d.forced && <Badge tone="warn">forced</Badge>}
        <Cost entry={entry} />
      </p>
      {d.reason && <p className="text-sm text-zinc-700 dark:text-zinc-300">REASON: {d.reason}</p>}
      {d.action === "final" ? (
        <p className="font-mono text-xs">FINAL (the answer is shown in the conversation)</p>
      ) : (
        <ul className="space-y-1">
          {d.delegations.map((x) => (
            <li key={x.worker} className="rounded bg-zinc-100 p-2 font-mono text-xs dark:bg-zinc-900">
              <span className="font-semibold">DELEGATE: {x.worker}</span>
              <span className="block whitespace-pre-wrap">TASK: {x.task}</span>
            </li>
          ))}
          {d.delegations.length > 1 && <li className="text-xs">These workers ran in parallel.</li>}
        </ul>
      )}
    </div>
  );
}

function ResultEntry({ entry, run, open }: { entry: Entry; run: RunView; open: boolean }) {
  const r = entry.result!;
  return (
    <details open={open} className="group">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm font-medium">
        <span>Result from {agentTitle(r.worker)}</span>
        {r.failed && <Badge tone="bad">failed</Badge>}
        {r.unsourced && <Badge tone="warn">unsourced</Badge>}
        {r.sources.length > 0 && <Badge>cites {r.sources.map((n) => `[${n}]`).join("")}</Badge>}
        <Cost entry={entry} />
      </summary>
      <div className="mt-2 border-l-2 border-zinc-200 pl-3 text-sm dark:border-zinc-800">
        {r.worker === "reviewer" && !r.failed ? (
          <ReviewView data={r.data} />
        ) : r.worker === "fact_checker" && !r.failed ? (
          <FactCheckTable data={r.data} />
        ) : (
          <Markdown text={r.content} sources={run.sources} runId={run.run_id} />
        )}
      </div>
    </details>
  );
}

/** The conversation history of one run: Supervisor decisions, worker results, notices and
 * human feedback, in order. The latest worker result is open. */
export default function Transcript({ run }: { run: RunView }) {
  const lastResult = [...run.transcript].reverse().find((e) => e.kind === "worker_result")?.seq;
  if (run.transcript.length === 0) {
    return <p className="text-sm text-zinc-600 dark:text-zinc-400">Nothing yet: the Supervisor is about to decide.</p>;
  }
  return (
    <ol aria-label="Transcript" className="space-y-3">
      {run.transcript.map((entry) => (
        <li key={entry.seq} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
          {entry.kind === "decision" && entry.decision && <DecisionEntry entry={entry} limit={run.iteration_limit} />}
          {entry.kind === "worker_result" && entry.result && (
            <ResultEntry entry={entry} run={run} open={entry.seq === lastResult} />
          )}
          {entry.kind === "feedback" && (
            <p className="text-sm">
              <span className="font-medium">Your feedback:</span> {entry.text}
            </p>
          )}
          {entry.kind === "notice" && (
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              <span className="font-medium">Note:</span> {entry.text}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
