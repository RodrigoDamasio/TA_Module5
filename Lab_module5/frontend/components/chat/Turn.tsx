"use client";
import ApprovalPanel from "@/components/ApprovalPanel";
import Badge from "@/components/Badge";
import MetaBar from "@/components/MetaBar";
import FinalAnswer from "@/components/answer/FinalAnswer";
import { agentTitle, type Board, working } from "@/lib/agents";
import { plural } from "@/lib/format";
import type { RunView } from "@/lib/schemas";

export interface TurnProps {
  task: string;
  view: RunView | null;
  missing: boolean;
  board: Board | null; // live or replay board (null for stored runs)
  lost: boolean;
  selected: boolean;
  sample: boolean;
  busy: boolean;
  feedbackMax: number;
  onSelect: () => void;
  onApprove: () => void;
  onReject: (feedback: string | null) => void;
  onOpenRun: (runId: string, task: string) => void;
  onRemove: () => void;
  onRunForReal?: () => void;
}

function Progress({ view, board, lost }: { view: RunView; board: Board | null; lost: boolean }) {
  const names = board ? working(board) : [];
  const who = names.length
    ? `${names.map(agentTitle).join(" and ")} ${names.length > 1 ? "are" : "is"} working`
    : view.status === "queued"
      ? "Waiting in the queue"
      : "Working";
  const iteration = board?.iteration ?? view.iteration;
  const limit = board?.iterationLimit || view.iteration_limit;
  return (
    <div className="space-y-1 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <span className="inline-block size-2 rounded-full bg-orange-600 motion-safe:animate-pulse" aria-hidden />
        <span className="font-medium">{who}…</span>
        <span className="text-zinc-600 dark:text-zinc-400">decision {Math.min(iteration, limit)} of {limit}</span>
      </p>
      {lost && <p className="text-xs">Live updates interrupted — refreshing every few seconds.</p>}
    </div>
  );
}

export default function Turn(p: TurnProps) {
  const v = p.view;
  return (
    <li className="space-y-3">
      <div className="ml-auto max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm whitespace-pre-wrap dark:bg-zinc-800">
        <span className="sr-only">You: </span>
        {p.task || v?.task || "(task)"}
      </div>
      <div
        className={`space-y-3 rounded-lg border p-3 ${p.selected ? "border-orange-600 dark:border-orange-500" : "border-zinc-200 dark:border-zinc-800"}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold">Research assistant</span>
          <div className="flex flex-wrap items-center gap-2">
            {p.sample && <Badge tone="accent">Stored result — replay (0 AI calls)</Badge>}
            {v && (
              <button type="button" onClick={p.onSelect} aria-pressed={p.selected} className="text-xs font-medium text-orange-800 underline dark:text-orange-300">
                {p.selected ? "Showing agents and transcript" : "Show agents and transcript"}
              </button>
            )}
          </div>
        </div>

        {p.missing ? (
          <div className="space-y-2 text-sm">
            <p>This run is no longer available (runs are kept for 30 days).</p>
            <button type="button" onClick={p.onRemove} className="font-medium underline">
              Remove from the conversation
            </button>
          </div>
        ) : !v ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        ) : (
          <>
            {v.flags.includes("possible_injection") && (
              <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">
                Phrases often used in prompt-injection attempts were found in this task. The agents
                treated them as data, not as instructions.
              </p>
            )}
            {v.memory_used.length > 0 && (
              <div className="text-xs">
                Used memory from {plural(v.memory_used.length, "earlier task")}:{" "}
                {v.memory_used.map((m, i) => (
                  <span key={m.run_id}>
                    {i > 0 && ", "}
                    <button type="button" onClick={() => p.onOpenRun(m.run_id, m.task)} className="underline">
                      {m.task}
                    </button>
                  </span>
                ))}
              </div>
            )}
            {(v.status === "running" || v.status === "queued") && <Progress view={v} board={p.board} lost={p.lost} />}
            {v.status === "awaiting_approval" &&
              (p.sample ? (
                <p className="text-sm">This stored run was waiting for approval.</p>
              ) : (
                <ApprovalPanel run={v} busy={p.busy} feedbackMax={p.feedbackMax} onApprove={p.onApprove} onReject={p.onReject} />
              ))}
            {v.status === "completed" && <FinalAnswer run={v} />}
            {v.status === "failed" && (
              <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
                The run failed: {v.error ?? "unknown error"}
              </p>
            )}
            {v.status === "cancelled" && <p className="text-sm">This run was cancelled.</p>}
            {(v.status === "completed" || v.status === "failed") && <MetaBar run={v} />}
            {p.sample && p.onRunForReal && v.status === "completed" && (
              <button type="button" onClick={p.onRunForReal} className="text-sm font-medium text-orange-800 underline dark:text-orange-300">
                Run it for real
              </button>
            )}
          </>
        )}
      </div>
    </li>
  );
}
