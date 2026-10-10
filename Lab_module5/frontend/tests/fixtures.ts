/** Fixtures built from REAL stored runs (backend/samples/runs, exported by the evaluation),
 * parsed with the frontend's schemas: the contract is checked on real data. */
import injectionJson from "../../backend/samples/runs/http-caching-injection.json";
import ragJson from "../../backend/samples/runs/rag-vs-finetuning.json";
import { type Entry, type Health, type RunView, RunViewSchema } from "@/lib/schemas";

export const ragRun: RunView = RunViewSchema.parse({ ...ragJson, sample: false });
export const injectionRun: RunView = RunViewSchema.parse({ ...injectionJson, sample: false });

export function runView(overrides: Partial<RunView> = {}): RunView {
  return { ...ragRun, ...overrides };
}

/** The rag run as it looked while running: the first n entries, no answer yet. */
export function partial(n: number, overrides: Partial<RunView> = {}): RunView {
  return runView({
    status: "running",
    final_output: null,
    transcript: ragRun.transcript.slice(0, n),
    meta: { ...ragRun.meta, finished_at: null, duration_ms: null },
    ...overrides,
  });
}

export function entry(overrides: Partial<Entry>): Entry {
  return {
    seq: 1,
    iteration: 1,
    kind: "notice",
    agent: "system",
    task: null,
    text: "note",
    flag: null,
    model: null,
    tokens: { input: 0, output: 0, thinking: 0 },
    llm_calls: 0,
    cached_calls: 0,
    cached: false,
    duration_ms: 0,
    decision: null,
    result: null,
    ...overrides,
  };
}

export const health: Health = {
  status: "ok",
  service_level: "full",
  service_reason: null,
  retry_after_s: null,
  llm_mode: "fake",
  wikipedia: "fake",
  models: { supervisor: "demo", workers: "demo" },
  prompt_version: "2",
  usage_today: { calls: 0, limit: 900 },
  limits: {
    task_min_chars: 10,
    task_max_chars: 2000,
    default_max_iterations: 5,
    max_iterations_limit: 8,
    max_parallel_delegations: 2,
    approval_timeout_min: 30,
    feedback_max_chars: 1000,
  },
};

export const agentsList = [
  { name: "supervisor", title: "Supervisor", role: "supervisor" as const, description: "decides" },
  { name: "researcher", title: "Researcher", role: "worker" as const, description: "finds" },
  { name: "writer", title: "Writer", role: "worker" as const, description: "writes" },
  { name: "reviewer", title: "Reviewer", role: "worker" as const, description: "reviews" },
  { name: "fact_checker", title: "Fact-Checker", role: "worker" as const, description: "checks" },
];

export const samplesList = [
  { id: "rag-vs-finetuning", title: "RAG or fine-tuning?", task: ragRun.task },
  { id: "http-caching-injection", title: "HTTP caching", task: injectionRun.task },
];
