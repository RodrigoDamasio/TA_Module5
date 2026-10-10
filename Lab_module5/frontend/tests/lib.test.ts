import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AGENT_ORDER,
  agentTitle,
  boardFromRun,
  emptyBoard,
  eventsFromRun,
  reduce,
  resultNote,
  working,
} from "@/lib/agents";
import { linkCitations, safeUrl } from "@/lib/citations";
import { parseEvent, subscribe } from "@/lib/events";
import { domain, flagLabel, formatCost, formatDuration, formatMs, plural, shorten } from "@/lib/format";
import { replayFrames } from "@/lib/replay";
import type { RunEvent } from "@/lib/schemas";
import { addToThread, loadThread, MAX_THREAD, removeFromThread, saveThread, THREAD_KEY } from "@/lib/thread";
import { entry, partial, ragRun, runView } from "./fixtures";

const ev = (e: Omit<RunEvent, "id">, id = 1) => ({ ...e, id }) as RunEvent;

describe("agent board reducer", () => {
  it("follows a run: deciding, working, done, and the feed", () => {
    let b = emptyBoard();
    b = reduce(b, ev({ type: "run_started", data: { iteration: 0, iteration_limit: 5 } }), 0);
    b = reduce(b, ev({ type: "agent_started", data: { agent: "supervisor", iteration: 0, task: null } }), 1000);
    expect(working(b)).toEqual(["supervisor"]);
    b = reduce(b, ev({ type: "decision", data: ragRun.transcript[0] }), 2000);
    expect(b.cards.supervisor.state).toBe("done");
    b = reduce(b, ev({ type: "agent_started", data: { agent: "researcher", iteration: 1, task: "Topics: RAG" } }), 2000);
    expect(b.cards.researcher).toMatchObject({ state: "working", task: "Topics: RAG", since: 2000, turns: 1 });
    b = reduce(b, ev({ type: "worker_result", data: ragRun.transcript[1] }), 5000);
    expect(b.cards.researcher.state).toBe("done");
    expect(b.cards.researcher.note).toMatch(/source\(s\) cited/);
    expect(b.feed.map((l) => l.text)).toEqual([
      "Run started: up to 5 Supervisor decisions",
      "Supervisor is deciding (decision 1 of 5)",
      "Supervisor → Researcher",
      "Researcher started: Topics: RAG",
      expect.stringMatching(/^Researcher finished: \d source\(s\) cited$/),
    ]);
  });

  it("rebuilds a finished run with parallel workers from its transcript", () => {
    const b = boardFromRun(ragRun);
    expect(b.status).toBe("completed");
    expect(b.iteration).toBe(4);
    for (const name of AGENT_ORDER) expect(b.cards[name].state).toBe("done");
    expect(b.feed.some((l) => l.text === "Supervisor → Reviewer + Fact-Checker (in parallel)")).toBe(true);
    expect(b.cards.reviewer.note).toMatch(/^approve · \d issues?$/);
    expect(b.cards.fact_checker.note).toMatch(/claims supported$/);
    const events = eventsFromRun(ragRun);
    const i = events.findIndex((e) => e.type === "decision" && e.data.decision?.delegations.length === 2);
    expect(events.slice(i + 1, i + 3).map((e) => e.type)).toEqual(["agent_started", "agent_started"]);
  });

  it("approval, feedback, failure and cancellation", () => {
    let b = boardFromRun(partial(2));
    b = reduce(b, ev({ type: "agent_started", data: { agent: "writer", iteration: 2, task: "Write" } }), 0);
    b = reduce(b, ev({ type: "awaiting_approval", data: { draft: "d", expires_at: "x" } }), 0);
    expect(b.status).toBe("awaiting_approval");
    expect(working(b)).toEqual([]);
    b = reduce(b, ev({ type: "feedback", data: entry({ kind: "feedback", agent: "human", text: "More please" }) }), 0);
    expect(b.status).toBe("queued");
    b = reduce(b, ev({ type: "run_started", data: { iteration: 4, iteration_limit: 6 } }), 0);
    expect(b.feed.at(-1)?.text).toBe("Revising after your feedback (2 more decisions)");
    b = reduce(b, ev({ type: "agent_started", data: { agent: "writer", iteration: 4, task: "Revise" } }), 0);
    const failed = reduce(b, ev({ type: "failed", data: { error: "quota" } }), 0);
    expect(failed.cards.writer.state).toBe("failed");
    expect(failed.feed.at(-1)?.text).toBe("Run failed: quota");
    const cancelled = reduce(b, ev({ type: "cancelled", data: { reason: "expired" } }), 0);
    expect(cancelled.cards.writer.state).toBe("idle");
    const done = reduce(b, ev({ type: "completed", data: { final_output: "x", forced: true, degraded: true } }), 0);
    expect(done.feed.at(-1)?.text).toBe("Answer ready (assembled automatically)");
    expect(reduce(b, ev({ type: "notice", data: entry({ text: "Used 1 memories" }) }), 0).feed.at(-1)?.text).toBe("Used 1 memories");
  });

  it("forced and repaired decisions, failed results, stored states", () => {
    const forced = entry({ kind: "decision", agent: "supervisor", decision: { action: "final", delegations: [], final: "x", reason: null, repaired: false, forced: true } });
    let b = reduce(emptyBoard(), ev({ type: "decision", data: forced }), 0);
    expect(b.feed.at(-1)?.text).toBe("Supervisor wrote the final answer (forced: no decisions left)");
    const repaired = entry({ kind: "decision", decision: { action: "delegate", delegations: [{ worker: "writer", task: "w" }], final: null, reason: null, repaired: true, forced: false } });
    b = reduce(b, ev({ type: "decision", data: repaired }), 0);
    expect(b.feed.at(-1)?.text).toBe("Supervisor → Writer · reply repaired");
    const failedResult = entry({ kind: "worker_result", agent: "writer", result: { worker: "writer", content: "x", data: {}, sources: [], unsourced: false, failed: true } });
    expect(resultNote(failedResult)).toBe("could not finish");
    expect(reduce(b, ev({ type: "worker_result", data: failedResult }), 0).cards.writer.state).toBe("failed");
    expect(resultNote(entry({}))).toBe("");
    const unsourced = entry({ result: { worker: "researcher", content: "x", data: {}, sources: [], unsourced: true, failed: false } });
    expect(resultNote(unsourced)).toBe("notes without sources");
    expect(boardFromRun(runView({ status: "failed", error: "boom" })).status).toBe("failed");
    expect(boardFromRun(runView({ status: "cancelled" })).status).toBe("cancelled");
    expect(boardFromRun(runView({ status: "awaiting_approval", approval: { required: true, draft: "d", expires_at: "x", revisions: 0 } })).status).toBe("awaiting_approval");
    expect(agentTitle("fact_checker")).toBe("Fact-Checker");
    expect(agentTitle("new_worker")).toBe("New worker");
  });

  it("replay frames: every event, parallel starts without extra delay", () => {
    const frames = replayFrames(ragRun);
    expect(frames.length).toBe(eventsFromRun(ragRun).length);
    const zero = frames.filter((f) => f.delayMs === 0);
    expect(zero.length).toBe(1);
    expect(frames.at(-1)?.event.type).toBe("completed");
  });
});

describe("citations and safe links", () => {
  const known = new Set([1, 2]);
  const anchor = (n: number) => `#run-source-${n}`;
  it("links known citations outside code only", () => {
    expect(linkCitations("A [1] and [3] and [1, 2].", known, anchor)).toBe(
      "A [\\[1\\]](#run-source-1) and [3] and [\\[1\\]](#run-source-1)[\\[2\\]](#run-source-2).",
    );
    expect(linkCitations("`code [1]` and [2]", known, anchor)).toBe("`code [1]` and [\\[2\\]](#run-source-2)");
    expect(linkCitations("```\nx [1]\n```\n[1]", known, anchor)).toBe("```\nx [1]\n```\n[\\[1\\]](#run-source-1)");
    expect(linkCitations("[1](http://x)", known, anchor)).toBe("[1](http://x)");
  });
  it("keeps only http(s) and anchors", () => {
    expect(safeUrl("https://en.wikipedia.org/wiki/X")).toBe("https://en.wikipedia.org/wiki/X");
    expect(safeUrl("#run-source-1")).toBe("#run-source-1");
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl("data:text/html,x")).toBe("");
    expect(safeUrl("not a url")).toBe("");
  });
});

describe("thread storage", () => {
  afterEach(() => window.localStorage.clear());
  const item = (n: number) => ({ run_id: `run_${n.toString(16).padStart(4, "0")}`, task: `t${n}`, created_at: "x" });

  it("adds, moves to the end, caps and removes", () => {
    let items = addToThread([], item(1));
    items = addToThread(items, item(2));
    items = addToThread(items, item(1));
    expect(items.map((i) => i.task)).toEqual(["t2", "t1"]);
    for (let n = 3; n < 30; n++) items = addToThread(items, item(n));
    expect(items).toHaveLength(MAX_THREAD);
    expect(removeFromThread(items, items[0].run_id)).toHaveLength(MAX_THREAD - 1);
  });

  it("round-trips through localStorage and ignores bad data", () => {
    saveThread([item(1)]);
    expect(loadThread()).toEqual([item(1)]);
    window.localStorage.setItem(THREAD_KEY, "{not json");
    expect(loadThread()).toEqual([]);
    window.localStorage.setItem(THREAD_KEY, JSON.stringify([{ run_id: "evil", task: 1 }]));
    expect(loadThread()).toEqual([]);
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveThread([item(1)])).not.toThrow();
    expect(loadThread()).toEqual([]);
    vi.restoreAllMocks();
  });
});

describe("format", () => {
  it("formats durations, costs, domains and text", () => {
    expect(formatMs(450)).toBe("450 ms");
    expect(formatMs(2500)).toBe("2.5 s");
    expect(formatMs(65_000)).toBe("1 min 5 s");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(125)).toBe("2 min 5 s");
    expect(formatDuration(18_000)).toBe("about 5 h");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00001)).toBe("< $0.0001");
    expect(formatCost(0.002825)).toBe("$0.0028");
    expect(domain("https://en.wikipedia.org/wiki/X")).toBe("en.wikipedia.org");
    expect(domain("nope")).toBe("");
    expect(shorten("a  b\n c", 10)).toBe("a b c");
    expect(shorten("abcdefghijk", 5)).toBe("abcd…");
    expect(plural(1, "source")).toBe("1 source");
    expect(plural(3, "source")).toBe("3 sources");
    expect(flagLabel("possible_injection")).toBe("possible prompt injection");
    expect(flagLabel("new_flag")).toBe("new flag");
  });
});

describe("events", () => {
  class FakeES {
    static CLOSED = 2;
    static last: FakeES;
    readyState = 1;
    closed = false;
    onerror: (() => void) | null = null;
    listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
    constructor(public url: string) {
      FakeES.last = this;
    }
    addEventListener(type: string, fn: (e: MessageEvent) => void) {
      (this.listeners[type] ??= []).push(fn);
    }
    close() {
      this.closed = true;
      this.readyState = 2;
    }
    emit(type: string, data: unknown, id = 1) {
      const raw = { data: typeof data === "string" ? data : JSON.stringify(data), lastEventId: String(id) } as MessageEvent;
      this.listeners[type]?.forEach((fn) => fn(raw));
    }
  }

  it("parses events, closes on a terminal one, reports invalid ones", () => {
    const seen: string[] = [];
    let invalid = 0;
    subscribe("u", { onEvent: (e) => seen.push(e.type), onLost: () => {}, onInvalid: () => invalid++ }, FakeES as never);
    const es = FakeES.last;
    es.emit("run_started", { iteration: 0, iteration_limit: 5 }, 3);
    es.emit("decision", ragRun.transcript[0], 4);
    es.emit("decision", { nope: true });
    es.emit("worker_result", "{broken");
    es.emit("completed", { final_output: "x", forced: false, degraded: false });
    expect(seen).toEqual(["run_started", "decision", "completed"]);
    expect(invalid).toBe(2);
    expect(es.closed).toBe(true);
    expect(parseEvent("failed", { data: JSON.stringify({ error: "x" }), lastEventId: "9" } as MessageEvent)).toEqual({ id: 9, type: "failed", data: { error: "x" } });
  });

  it("reports a lost stream (CLOSED), not a reconnect (CONNECTING)", () => {
    let lost = 0;
    subscribe("u", { onEvent: () => {}, onLost: () => lost++, onInvalid: () => {} }, FakeES as never);
    const es = FakeES.last;
    es.readyState = 0;
    es.onerror?.();
    expect(lost).toBe(0);
    es.readyState = 2;
    es.onerror?.();
    es.onerror?.();
    expect(lost).toBe(1);
    let noImpl = 0;
    subscribe("u", { onEvent: () => {}, onLost: () => noImpl++, onInvalid: () => {} }, undefined).close();
    expect(noImpl).toBe(1);
  });
});
