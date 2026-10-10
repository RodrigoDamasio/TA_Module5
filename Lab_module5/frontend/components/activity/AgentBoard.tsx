"use client";
import { useNow } from "@/hooks/useNow";
import { AGENT_ORDER, agentTitle, type Board, type Card } from "@/lib/agents";
import { formatMs, shorten } from "@/lib/format";
import type { Agent } from "@/lib/schemas";

const STATE_STYLE: Record<Card["state"], string> = {
  idle: "border-zinc-200 dark:border-zinc-800",
  working: "border-orange-600 bg-orange-50 dark:border-orange-500 dark:bg-orange-950",
  done: "border-emerald-600 dark:border-emerald-600",
  failed: "border-red-600 dark:border-red-500",
};
const STATE_TEXT: Record<Card["state"], string> = {
  idle: "○ idle",
  working: "● working",
  done: "✓ done",
  failed: "✕ failed",
};

function AgentCard({ name, card, agent, now }: { name: string; card: Card; agent?: Agent; now: number | null }) {
  const elapsed = card.state === "working" && card.since && now ? Math.max(0, now - card.since) : null;
  return (
    <li className={`rounded-md border-2 p-2 ${STATE_STYLE[card.state]}`} aria-label={`${agentTitle(name)}: ${card.state}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{agent?.title ?? agentTitle(name)}</span>
        <span className={`text-xs font-medium ${card.state === "working" ? "text-orange-800 motion-safe:animate-pulse dark:text-orange-300" : "text-zinc-700 dark:text-zinc-300"}`}>
          {STATE_TEXT[card.state]}
          {elapsed !== null && elapsed >= 1000 ? ` · ${formatMs(elapsed)}` : ""}
        </span>
      </div>
      {card.state === "working" && card.task && (
        <p className="mt-1 text-xs text-zinc-700 dark:text-zinc-300">{shorten(card.task, 120)}</p>
      )}
      {card.state !== "working" && card.note && (
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{card.note}</p>
      )}
    </li>
  );
}

/** One card per agent; two cards can be working at once (parallel workers). */
export default function AgentBoard({ board, agents }: { board: Board; agents: Agent[] }) {
  const now = useNow(1000);
  const names = agents.length ? agents.map((a) => a.name) : AGENT_ORDER;
  const byName = new Map(agents.map((a) => [a.name, a]));
  return (
    <section aria-labelledby="agents-title" className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="agents-title" className="text-sm font-semibold tracking-wide uppercase">
          Agents
        </h2>
        {board.iterationLimit > 0 && (
          <span className="text-xs text-zinc-600 dark:text-zinc-400">
            decision {Math.min(board.iteration, board.iterationLimit)} of {board.iterationLimit}
          </span>
        )}
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1">
        {names.map((name) => (
          <AgentCard
            key={name}
            name={name}
            card={board.cards[name] ?? { state: "idle", task: null, since: null, note: null, turns: 0 }}
            agent={byName.get(name)}
            now={now}
          />
        ))}
      </ul>
    </section>
  );
}
