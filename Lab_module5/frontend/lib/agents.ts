/** The agent board as a pure reducer over run events. The same reducer runs over live SSE
 * events, over a stored run's transcript (reload, finished runs) and over a sample replay,
 * so the board is right however the page got there. */
import { shorten } from "./format";
import {
  type Entry,
  FactCheckDataSchema,
  ReviewDataSchema,
  type RunEvent,
  type RunStatus,
  type RunView,
} from "./schemas";

export type CardState = "idle" | "working" | "done" | "failed";

export interface Card {
  state: CardState;
  task: string | null;
  since: number | null; // ms timestamp when it started working
  note: string | null; // short result summary
  turns: number; // how many times it worked in this run
}

export interface FeedLine {
  id: number;
  agent: string;
  text: string;
}

export interface Board {
  status: RunStatus | "idle";
  iteration: number;
  iterationLimit: number;
  cards: Record<string, Card>;
  feed: FeedLine[];
}

export const AGENT_ORDER = ["supervisor", "researcher", "writer", "reviewer", "fact_checker"];

const TITLES: Record<string, string> = {
  supervisor: "Supervisor",
  researcher: "Researcher",
  writer: "Writer",
  reviewer: "Reviewer",
  fact_checker: "Fact-Checker",
  human: "You",
  system: "System",
};

export function agentTitle(name: string): string {
  return TITLES[name] ?? name.charAt(0).toUpperCase() + name.slice(1).replaceAll("_", " ");
}

const idleCard = (): Card => ({ state: "idle", task: null, since: null, note: null, turns: 0 });

export function emptyBoard(names: string[] = AGENT_ORDER): Board {
  return {
    status: "idle",
    iteration: 0,
    iterationLimit: 0,
    cards: Object.fromEntries(names.map((n) => [n, idleCard()])),
    feed: [],
  };
}

export function working(board: Board): string[] {
  return Object.entries(board.cards)
    .filter(([, c]) => c.state === "working")
    .map(([n]) => n);
}

/** One-line summary of a worker result for its card and the feed. */
export function resultNote(entry: Entry): string {
  const r = entry.result;
  if (!r) return "";
  if (r.failed) return "could not finish";
  if (r.worker === "researcher") {
    return r.unsourced ? "notes without sources" : `${r.sources.length} source(s) cited`;
  }
  if (r.worker === "reviewer") {
    const review = ReviewDataSchema.safeParse(r.data);
    if (review.success) {
      const n = review.data.issues.length;
      return `${review.data.verdict} · ${n} issue${n === 1 ? "" : "s"}`;
    }
  }
  if (r.worker === "fact_checker") {
    const check = FactCheckDataSchema.safeParse(r.data);
    if (check.success) {
      const ok = check.data.claims.filter((c) => c.status === "supported").length;
      return `${ok}/${check.data.claims.length} claims supported`;
    }
  }
  if (r.worker === "writer") return "draft ready";
  return "done";
}

function setCard(board: Board, name: string, patch: Partial<Card>): Record<string, Card> {
  const current = board.cards[name] ?? idleCard();
  return { ...board.cards, [name]: { ...current, ...patch } };
}

function finishWorking(cards: Record<string, Card>, to: CardState): Record<string, Card> {
  return Object.fromEntries(
    Object.entries(cards).map(([n, c]) => [n, c.state === "working" ? { ...c, state: to } : c]),
  );
}

export function reduce(board: Board, event: RunEvent, now: number): Board {
  const line = (agent: string, text: string): FeedLine[] => [
    ...board.feed,
    { id: board.feed.length + 1, agent, text },
  ];
  switch (event.type) {
    case "run_started": {
      const { iteration, iteration_limit } = event.data;
      const text =
        iteration > 0
          ? `Revising after your feedback (${iteration_limit - iteration} more decisions)`
          : `Run started: up to ${iteration_limit} Supervisor decisions`;
      return { ...board, status: "running", iteration, iterationLimit: iteration_limit, feed: line("system", text) };
    }
    case "agent_started": {
      const { agent, iteration, task } = event.data;
      const prev = board.cards[agent] ?? idleCard();
      const cards = setCard(board, agent, { state: "working", task, since: now, turns: prev.turns + 1 });
      const text =
        agent === "supervisor"
          ? `Supervisor is deciding (decision ${iteration + 1} of ${board.iterationLimit || "?"})`
          : `${agentTitle(agent)} started: ${shorten(task ?? "", 90)}`;
      return { ...board, status: "running", cards, feed: line(agent, text) };
    }
    case "decision": {
      const d = event.data.decision;
      if (!d) return board;
      const delegations = d.delegations.map((x) => agentTitle(x.worker));
      const note = d.action === "final" ? "wrote the final answer" : `delegated to ${delegations.join(" + ")}`;
      const cards = setCard(board, "supervisor", { state: "done", note });
      let text: string;
      if (d.action === "final") {
        text = `Supervisor wrote the final answer${d.forced ? " (forced: no decisions left)" : ""}`;
      } else {
        const parallel = delegations.length > 1 ? " (in parallel)" : "";
        text = `Supervisor → ${delegations.join(" + ")}${parallel}${d.repaired ? " · reply repaired" : ""}`;
      }
      return { ...board, iteration: Math.max(board.iteration, event.data.iteration), cards, feed: line("supervisor", text) };
    }
    case "worker_result": {
      const r = event.data.result;
      if (!r) return board;
      const note = resultNote(event.data);
      const cards = setCard(board, r.worker, { state: r.failed ? "failed" : "done", note });
      return { ...board, cards, feed: line(r.worker, `${agentTitle(r.worker)} finished: ${note}`) };
    }
    case "notice":
      return { ...board, feed: line("system", event.data.text ?? "") };
    case "feedback":
      return {
        ...board,
        status: "queued",
        feed: line("human", `Your feedback: ${shorten(event.data.text ?? "", 90)}`),
      };
    case "awaiting_approval":
      return {
        ...board,
        status: "awaiting_approval",
        cards: finishWorking(board.cards, "done"),
        feed: line("system", "Waiting for your approval"),
      };
    case "completed": {
      const { forced, degraded } = event.data;
      const how = degraded ? " (assembled automatically)" : forced ? " (forced completion)" : "";
      return { ...board, status: "completed", cards: finishWorking(board.cards, "done"), feed: line("system", `Answer ready${how}`) };
    }
    case "failed":
      return {
        ...board,
        status: "failed",
        cards: finishWorking(board.cards, "failed"),
        feed: line("system", `Run failed: ${event.data.error}`),
      };
    case "cancelled":
      return {
        ...board,
        status: "cancelled",
        cards: finishWorking(board.cards, "idle"),
        feed: line("system", `Run cancelled: ${event.data.reason}`),
      };
  }
}

/** A stored run as the event sequence that produced it (for reloads and replays). */
export function eventsFromRun(run: RunView): RunEvent[] {
  const events: RunEvent[] = [];
  let id = 0;
  const push = (e: Omit<RunEvent, "id">) => events.push({ ...e, id: --id } as RunEvent);
  push({ type: "run_started", data: { iteration: 0, iteration_limit: run.max_iterations } });
  const started = new Set<string>();
  for (const entry of run.transcript) {
    if (entry.kind === "decision") {
      push({ type: "agent_started", data: { agent: "supervisor", iteration: entry.iteration - 1, task: null } });
      push({ type: "decision", data: entry });
      // Parallel delegations start together; their results follow.
      for (const d of entry.decision?.delegations ?? []) {
        push({ type: "agent_started", data: { agent: d.worker, iteration: entry.iteration, task: d.task } });
        started.add(d.worker);
      }
    } else if (entry.kind === "worker_result") {
      const worker = entry.result?.worker ?? entry.agent;
      if (!started.has(worker)) {
        push({ type: "agent_started", data: { agent: worker, iteration: entry.iteration, task: entry.task } });
      }
      started.delete(worker);
      push({ type: "worker_result", data: entry });
    } else if (entry.kind === "feedback") {
      push({ type: "feedback", data: entry });
      push({ type: "run_started", data: { iteration: entry.iteration, iteration_limit: run.iteration_limit } });
    } else {
      push({ type: "notice", data: entry });
    }
  }
  if (run.status === "completed" && run.final_output !== null) {
    push({ type: "completed", data: { final_output: run.final_output, forced: run.forced, degraded: run.degraded } });
  } else if (run.status === "awaiting_approval") {
    push({ type: "awaiting_approval", data: { draft: run.approval.draft ?? "", expires_at: run.approval.expires_at ?? "" } });
  } else if (run.status === "failed") {
    push({ type: "failed", data: { error: run.error ?? "unknown error" } });
  } else if (run.status === "cancelled") {
    push({ type: "cancelled", data: { reason: "cancelled" } });
  }
  return events;
}

export function boardFromRun(run: RunView, names: string[] = AGENT_ORDER): Board {
  const board = eventsFromRun(run).reduce((b, e) => reduce(b, e, 0), emptyBoard(names));
  return { ...board, iteration: run.iteration, iterationLimit: run.iteration_limit };
}
