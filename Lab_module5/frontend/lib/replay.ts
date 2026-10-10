/** Sample replay (Lab 3): a stored run's events with delays, so the same components animate
 * it — agent board, feed, transcript — at 0 LLM calls. */
import { eventsFromRun } from "./agents";
import type { RunEvent, RunView } from "./schemas";

export interface Frame {
  delayMs: number; // wait before applying this event
  event: RunEvent;
}

const DELAYS: Partial<Record<RunEvent["type"], number>> = {
  run_started: 100,
  agent_started: 450,
  decision: 650,
  worker_result: 900,
  notice: 250,
};

export function replayFrames(run: RunView): Frame[] {
  const events = eventsFromRun(run);
  return events.map((event, i) => {
    // agent_started right after a parallel decision: no extra wait between the two starts
    const prev = events[i - 1];
    const parallelStart = event.type === "agent_started" && prev?.type === "agent_started";
    return { delayMs: parallelStart ? 0 : (DELAYS[event.type] ?? 500), event };
  });
}
