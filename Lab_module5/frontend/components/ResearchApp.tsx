"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ActivityFeed from "@/components/activity/ActivityFeed";
import AgentBoard from "@/components/activity/AgentBoard";
import Composer from "@/components/chat/Composer";
import RunSettings from "@/components/chat/RunSettings";
import Suggestions from "@/components/chat/Suggestions";
import Turn from "@/components/chat/Turn";
import ErrorBanner from "@/components/ErrorBanner";
import ServiceBanner from "@/components/ServiceBanner";
import Transcript from "@/components/transcript/Transcript";
import { useApiError } from "@/hooks/useApiError";
import { useHealth } from "@/hooks/useHealth";
import { type RunSource, useRun } from "@/hooks/useRun";
import { threadStore, useThread } from "@/hooks/useThread";
import { agentTitle, boardFromRun, working } from "@/lib/agents";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatDuration, plural, shorten } from "@/lib/format";
import { type Agent, type Limits, type RunView, type Sample, TERMINAL } from "@/lib/schemas";
import { addToThread, removeFromThread } from "@/lib/thread";

const FALLBACK_LIMITS: Limits = {
  task_min_chars: 10,
  task_max_chars: 2000,
  default_max_iterations: 5,
  max_iterations_limit: 8,
  max_parallel_delegations: 2,
  approval_timeout_min: 30,
  feedback_max_chars: 1000,
};
const REPLAY_ID = "replay";
type Tab = "answer" | "agents" | "transcript";
const TABS: { id: Tab; label: string }[] = [
  { id: "answer", label: "Answer" },
  { id: "agents", label: "Agents" },
  { id: "transcript", label: "Transcript" },
];

function setRunInUrl(runId: string | null) {
  const url = new URL(window.location.href);
  if (runId) url.searchParams.set("run", runId);
  else url.searchParams.delete("run");
  window.history.replaceState(null, "", url);
}

export default function ResearchApp({ initialRunId }: { initialRunId: string | null }) {
  const [thread, setThread] = useThread();
  const [views, setViews] = useState<Record<string, RunView>>({});
  const [missing, setMissing] = useState<Record<string, true>>({});
  const [agents, setAgents] = useState<Agent[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [replay, setReplay] = useState<RunView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("answer");
  const [task, setTask] = useState("");
  const [settings, setSettings] = useState<api.RunSettings | null>(null);
  const [posting, setPosting] = useState(false);
  const [acting, setActing] = useState(false);
  const { error, cooldown, fail, clear } = useApiError();
  const { health, level, retryAt } = useHealth();
  const requested = useRef(new Set<string>());

  const limits = health?.limits ?? FALLBACK_LIMITS;
  const runSettings: api.RunSettings = settings ?? {
    max_iterations: limits.default_max_iterations,
    require_approval: false,
    use_memory: true,
  };

  // ---- the thread: ?run= joins it; every run but the last is loaded once ---------------
  useEffect(() => {
    if (initialRunId && /^run_[a-f0-9]+$/.test(initialRunId)) {
      // The store, not `thread`: during hydration `thread` is still the empty server snapshot.
      const items = threadStore.get();
      if (!items.some((i) => i.run_id === initialRunId)) {
        threadStore.set(addToThread(items, { run_id: initialRunId, task: "", created_at: new Date().toISOString() }));
      }
    }
  }, [initialRunId]);

  useEffect(() => {
    api.agents().then(setAgents, () => {});
    api.samples().then(setSamples, () => {});
  }, []);

  const last = thread.at(-1) ?? null;
  useEffect(() => {
    for (const item of thread.slice(0, -1)) {
      if (requested.current.has(item.run_id)) continue;
      requested.current.add(item.run_id);
      api.getRun(item.run_id).then(
        (v) => setViews((all) => ({ ...all, [v.run_id]: v })),
        (err) => {
          if (err instanceof ApiError && err.kind === "not_found") {
            setMissing((m) => ({ ...m, [item.run_id]: true }));
          }
        },
      );
    }
  }, [thread]);

  // ---- the live run (the last one) and the sample replay ----------------------------------
  const liveId = last && !missing[last.run_id] ? last.run_id : null;
  const liveSource = useMemo<RunSource | null>(() => (liveId ? { kind: "live", id: liveId } : null), [liveId]);
  const onLiveView = useCallback((v: RunView) => setViews((all) => ({ ...all, [v.run_id]: v })), []);
  const live = useRun(liveSource, onLiveView);
  const replaySource = useMemo<RunSource | null>(() => (replay ? { kind: "replay", view: replay } : null), [replay]);
  const replayRun = useRun(replaySource);

  const liveMissing = live.error?.kind === "not_found";
  const viewOf = (id: string): RunView | null => (id === liveId ? live.view : null) ?? views[id] ?? null;
  const lastView = liveId ? viewOf(liveId) : null;
  const activeRun = lastView !== null && !TERMINAL.has(lastView.status) && lastView.status !== "awaiting_approval";

  // ---- selection: the replay, else the chosen run, else the last one ------------------------
  const selectedId = selected ?? (replay ? REPLAY_ID : last?.run_id ?? null);
  const selectedView = selectedId === REPLAY_ID ? replayRun.view : selectedId ? viewOf(selectedId) : null;
  const selectedBoard = useMemo(() => {
    if (selectedId === REPLAY_ID) return replayRun.board;
    if (selectedId && selectedId === liveId && live.view && !TERMINAL.has(live.view.status)) return live.board;
    return selectedView ? boardFromRun(selectedView) : null;
  }, [selectedId, liveId, live.board, live.view, replayRun.board, selectedView]);

  // ---- actions -----------------------------------------------------------------------------
  async function submit(text = task) {
    const clean = text.trim();
    setPosting(true);
    clear();
    try {
      const accepted = await api.startRun(clean, runSettings);
      setThread(addToThread(thread, { run_id: accepted.run_id, task: clean, created_at: new Date().toISOString() }));
      setTask("");
      setReplay(null);
      setSelected(null);
      setRunInUrl(accepted.run_id);
    } catch (err) {
      fail(err);
    } finally {
      setPosting(false);
    }
  }

  async function act(runId: string, action: () => Promise<RunView>) {
    setActing(true);
    clear();
    try {
      const v = await action();
      setViews((all) => ({ ...all, [v.run_id]: v }));
    } catch (err) {
      fail(err);
      api.getRun(runId).then(onLiveView, () => {});
    } finally {
      setActing(false);
    }
  }

  async function startReplay(s: Sample) {
    clear();
    try {
      setReplay(await api.sample(s.id));
      setSelected(null);
    } catch (err) {
      fail(err);
    }
  }

  function openRun(runId: string, runTask: string) {
    if (!thread.some((i) => i.run_id === runId)) {
      // older runs are inserted before the last one, so the live run stays the last
      const items = [...thread];
      items.splice(Math.max(0, items.length - 1), 0, { run_id: runId, task: runTask, created_at: new Date().toISOString() });
      setThread(items);
    }
    setSelected(runId);
  }

  function remove(runId: string) {
    setThread(removeFromThread(thread, runId));
    if (selected === runId) setSelected(null);
  }

  // ---- composer state ----------------------------------------------------------------------
  const length = task.trim().length;
  const disabledReason = posting
    ? "Sending…"
    : activeRun
      ? "Wait for the current run to finish."
      : level === "minimal"
        ? "Today's AI quota is used up."
        : cooldown > 0
          ? `You can send again in ${formatDuration(cooldown)}.`
          : length < limits.task_min_chars
            ? `Write at least ${limits.task_min_chars} characters.`
            : length > limits.task_max_chars
              ? `Keep the task under ${limits.task_max_chars} characters.`
              : null;

  // ---- one polite status line (not a live log: it would read whole answers aloud) ----------
  const statusLine = (() => {
    if (!lastView) return "";
    if (lastView.status === "awaiting_approval") return "Waiting for your approval.";
    if (lastView.status === "completed") return `Answer ready, ${plural(lastView.sources.length, "source")}.`;
    if (lastView.status === "failed") return "The run failed.";
    const names = working(live.board);
    return names.length ? `${names.map(agentTitle).join(" and ")} working.` : "Working.";
  })();

  const panelClass = (id: Tab) => `${tab === id ? "" : "hidden"} lg:block`;

  return (
    <div className="flex flex-1 flex-col gap-4">
      <ServiceBanner level={level} retryAt={retryAt} />
      <div role="tablist" aria-label="View" className="flex gap-1 border-b border-zinc-200 lg:hidden dark:border-zinc-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? "border-orange-700 text-orange-800 dark:text-orange-300" : "border-transparent text-zinc-600 dark:text-zinc-400"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <p role="status" className="sr-only">
        {statusLine}
      </p>

      <div className="grid flex-1 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <section id="panel-answer" role="tabpanel" aria-labelledby="tab-answer" aria-label="Conversation" className={`${panelClass("answer")} flex min-w-0 flex-col gap-4`}>
          {thread.length === 0 && !replay && (
            <div className="space-y-2 rounded-lg border border-dashed border-zinc-300 p-4 text-sm dark:border-zinc-700">
              <p className="font-medium">Ask a research question.</p>
              <p className="text-zinc-700 dark:text-zinc-300">
                A Supervisor agent delegates to a Researcher (Wikipedia), a Writer, a Reviewer and a
                Fact-Checker, then writes the answer with sources. Watch them work on the right.
              </p>
            </div>
          )}
          <ol className="flex flex-col gap-6">
            {thread.map((item) => {
              const isLive = item.run_id === liveId;
              return (
                <Turn
                  key={item.run_id}
                  task={item.task}
                  view={viewOf(item.run_id)}
                  missing={Boolean(missing[item.run_id]) || (isLive && liveMissing)}
                  board={isLive ? live.board : null}
                  lost={isLive && live.lost}
                  selected={selectedId === item.run_id}
                  sample={false}
                  busy={acting}
                  feedbackMax={limits.feedback_max_chars}
                  onSelect={() => {
                    setSelected(item.run_id);
                    setTab("agents");
                  }}
                  onApprove={() => act(item.run_id, () => api.approve(item.run_id))}
                  onReject={(feedback) => act(item.run_id, () => api.reject(item.run_id, feedback))}
                  onOpenRun={openRun}
                  onRemove={() => remove(item.run_id)}
                />
              );
            })}
            {replay && (
              <Turn
                task={replay.task}
                view={replayRun.view}
                missing={false}
                board={replayRun.board}
                lost={false}
                selected={selectedId === REPLAY_ID}
                sample
                busy={false}
                feedbackMax={limits.feedback_max_chars}
                onSelect={() => {
                  setSelected(REPLAY_ID);
                  setTab("agents");
                }}
                onApprove={() => {}}
                onReject={() => {}}
                onOpenRun={openRun}
                onRemove={() => setReplay(null)}
                onRunForReal={() => submit(replay.task)}
              />
            )}
          </ol>
          {live.error && !liveMissing && <ErrorBanner error={live.error} cooldown={0} />}
          {error && <ErrorBanner error={error} cooldown={cooldown} />}
          <Suggestions samples={samples} disabled={posting} onReplay={startReplay} />
          <Composer value={task} maxChars={limits.task_max_chars} disabledReason={disabledReason} busy={posting} onChange={setTask} onSubmit={() => submit()}>
            <RunSettings value={runSettings} maxIterations={limits.max_iterations_limit} onChange={setSettings} />
          </Composer>
        </section>

        <aside aria-label="Run details" className="flex min-w-0 flex-col gap-6 lg:sticky lg:top-4 lg:self-start">
          {selectedView && (
            <p className={`${tab === "answer" ? "hidden" : ""} text-xs text-zinc-600 lg:block dark:text-zinc-400`}>
              Selected run: <span className="font-medium text-zinc-800 dark:text-zinc-200">{shorten(selectedView.task, 80)}</span>
            </p>
          )}
          <div id="panel-agents" role="tabpanel" aria-labelledby="tab-agents" className={`${panelClass("agents")} space-y-6`}>
            {selectedBoard ? (
              <>
                <AgentBoard board={selectedBoard} agents={agents} />
                <ActivityFeed board={selectedBoard} />
              </>
            ) : (
              <p className="text-sm text-zinc-600 dark:text-zinc-400">The agents appear here when a run starts.</p>
            )}
          </div>
          <div id="panel-transcript" role="tabpanel" aria-labelledby="tab-transcript" className={`${panelClass("transcript")} space-y-2`}>
            <h2 className="text-sm font-semibold tracking-wide uppercase">Transcript</h2>
            {selectedView ? (
              <div role="region" aria-label="Transcript of the selected run" tabIndex={0} className="max-h-[70vh] overflow-y-auto pr-1">
                <Transcript run={selectedView} />
              </div>
            ) : (
              <p className="text-sm text-zinc-600 dark:text-zinc-400">Supervisor decisions and worker results appear here.</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
