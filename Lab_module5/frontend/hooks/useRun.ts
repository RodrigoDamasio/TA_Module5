import { useEffect, useRef, useState } from "react";
import { boardFromRun, type Board, emptyBoard, reduce } from "@/lib/agents";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { subscribe } from "@/lib/events";
import { replayFrames } from "@/lib/replay";
import { type RunEvent, type RunView, TERMINAL } from "@/lib/schemas";

export type RunSource = { kind: "live"; id: string } | { kind: "replay"; view: RunView };

export interface RunState {
  view: RunView | null;
  board: Board;
  lost: boolean; // live stream lost: polling instead
  error: ApiError | null;
}

const POLL_MS = 3000;
const REFETCH_DEBOUNCE_MS = 300;
const ENTRY_EVENTS = new Set(["decision", "worker_result", "notice", "feedback"]);

function sourceKey(source: RunSource | null): string | null {
  if (!source) return null;
  return source.kind === "live" ? source.id : `replay:${source.view.run_id}`;
}

/** Applies an event to the view: transcript entries are appended (by seq, no duplicates). */
export function applyToView(view: RunView | null, event: RunEvent): RunView | null {
  if (!view) return view;
  if (ENTRY_EVENTS.has(event.type)) {
    const entry = event.data as RunView["transcript"][number];
    if (view.transcript.some((e) => e.seq === entry.seq)) return view;
    return { ...view, status: "running", transcript: [...view.transcript, entry] };
  }
  if (event.type === "run_started") return { ...view, status: "running" };
  return view;
}

/** A replay starts from the stored run with nothing done yet. */
function blankReplay(view: RunView): RunView {
  return {
    ...view,
    status: "running",
    iteration: 0,
    transcript: [],
    final_output: null,
    sources: view.sources,
  };
}

/**
 * Follows one run. Live: GET the RunView (source of truth) and, unless it is finished,
 * subscribe to its events from the start (the board rebuilds itself); entry events extend
 * the transcript, approval and terminal events refetch. Lost stream → polling.
 * Replay: a stored run's events with delays, then the stored view.
 */
export function useRun(source: RunSource | null, onView?: (view: RunView) => void): RunState {
  const key = sourceKey(source);
  const [state, setState] = useState<RunState & { key: string | null }>({
    key: null,
    view: null,
    board: emptyBoard(),
    lost: false,
    error: null,
  });
  const onViewRef = useRef(onView);
  useEffect(() => {
    onViewRef.current = onView;
  });

  // A different run: reset during render (no effect needed).
  if (state.key !== key) {
    setState({
      key,
      view: source?.kind === "replay" ? blankReplay(source.view) : null,
      board: emptyBoard(),
      lost: false,
      error: null,
    });
  }

  const liveId = source?.kind === "live" ? source.id : null;
  const replayView = source?.kind === "replay" ? source.view : null;

  // ---- replay -----------------------------------------------------------------------------
  useEffect(() => {
    if (!replayView) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    let at = 0;
    for (const frame of replayFrames(replayView)) {
      at += frame.delayMs;
      timers.push(
        setTimeout(() => {
          setState((s) => ({
            ...s,
            board: reduce(s.board, frame.event, Date.now()),
            view: applyToView(s.view, frame.event),
          }));
        }, at),
      );
    }
    timers.push(
      setTimeout(() => setState((s) => ({ ...s, view: replayView, board: boardFromRun(replayView) })), at + 300),
    );
    return () => timers.forEach(clearTimeout);
  }, [replayView]);

  // ---- live -------------------------------------------------------------------------------
  useEffect(() => {
    if (!liveId) return;
    let cancelled = false;
    let poller: ReturnType<typeof setInterval> | null = null;
    let debounce: ReturnType<typeof setTimeout> | null = null;
    let subscription: { close: () => void } | null = null;

    const accept = (view: RunView, rebuildBoard: boolean) => {
      if (cancelled) return;
      setState((s) => ({ ...s, view, error: null, board: rebuildBoard ? boardFromRun(view) : s.board }));
      onViewRef.current?.(view);
      if (TERMINAL.has(view.status) && poller) {
        clearInterval(poller);
        poller = null;
      }
    };
    const fail = (err: unknown) => {
      if (cancelled) return;
      const error = err instanceof ApiError ? err : new ApiError("server", "Could not load the run.");
      setState((s) => ({ ...s, error }));
    };
    const refetch = () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => api.getRun(liveId).then((v) => accept(v, false), fail), REFETCH_DEBOUNCE_MS);
    };
    const poll = () => {
      setState((s) => ({ ...s, lost: true }));
      poller = setInterval(() => api.getRun(liveId).then((v) => accept(v, true), fail), POLL_MS);
    };

    api.getRun(liveId).then((view) => {
      if (cancelled) return;
      if (TERMINAL.has(view.status)) {
        accept(view, true);
        return;
      }
      accept(view, false);
      subscription = subscribe(api.eventsUrl(liveId), {
        onEvent: (event) => {
          if (cancelled) return;
          setState((s) => ({
            ...s,
            board: reduce(s.board, event, Date.now()),
            view: applyToView(s.view, event),
          }));
          if (!ENTRY_EVENTS.has(event.type) && event.type !== "agent_started") refetch();
        },
        onLost: poll,
        onInvalid: () => fail(new ApiError("invalid_response", "Unexpected update from the server.")),
      });
    }, fail);

    return () => {
      cancelled = true;
      subscription?.close();
      if (poller) clearInterval(poller);
      if (debounce) clearTimeout(debounce);
    };
  }, [liveId]);

  return { view: state.view, board: state.board, lost: state.lost, error: state.error };
}
