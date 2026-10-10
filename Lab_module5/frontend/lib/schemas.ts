/** Zod schemas mirroring the backend (app/api/schemas.py, app/domain/transcript.py,
 * app/api/routes.py). Every API response and every SSE event is parsed; invalid data is
 * never rendered. Unknown keys are dropped. */
import { z } from "zod";

const num = z.number();
const str = z.string();

// ---- problems (RFC 9457) ----------------------------------------------------------------

export const ProblemSchema = z.object({
  type: str.optional(),
  title: str.optional(),
  status: num.optional(),
  detail: str.optional(),
  instance: str.nullable().optional(),
  errors: z.array(z.object({ pointer: str, detail: str })).nullable().optional(),
});

// ---- transcript ----------------------------------------------------------------------------

export const TokensSchema = z.object({ input: num, output: num, thinking: num.optional() });

export const DecisionSchema = z.object({
  action: z.enum(["delegate", "final"]),
  delegations: z.array(z.object({ worker: str, task: str })),
  final: str.nullable(),
  reason: str.nullable(),
  repaired: z.boolean(),
  forced: z.boolean(),
});
export type Decision = z.infer<typeof DecisionSchema>;

export const ResultSchema = z.object({
  worker: str,
  content: str,
  data: z.record(str, z.unknown()),
  sources: z.array(num),
  unsourced: z.boolean(),
  failed: z.boolean(),
});
export type WorkerResult = z.infer<typeof ResultSchema>;

export const ENTRY_KINDS = ["decision", "worker_result", "feedback", "notice"] as const;

export const EntrySchema = z.object({
  seq: num,
  iteration: num,
  kind: z.enum(ENTRY_KINDS),
  agent: str,
  task: str.nullable(),
  text: str.nullable(),
  flag: str.nullable(),
  model: str.nullable(),
  tokens: TokensSchema,
  llm_calls: num,
  cached_calls: num,
  cached: z.boolean(),
  duration_ms: num,
  decision: DecisionSchema.nullable(),
  result: ResultSchema.nullable(),
});
export type Entry = z.infer<typeof EntrySchema>;

/** Structured worker data, parsed where it is shown. */
export const ReviewDataSchema = z.object({
  verdict: z.enum(["approve", "revise"]),
  issues: z.array(z.object({ severity: str, text: str })),
  balance_flags: z.array(str),
});
export const FactCheckDataSchema = z.object({
  claims: z.array(
    z.object({ sentence: str, status: str, source_n: num.nullable(), note: str.optional() }),
  ),
});

// ---- runs ------------------------------------------------------------------------------------

export const RUN_STATUSES = [
  "queued",
  "running",
  "awaiting_approval",
  "completed",
  "failed",
  "cancelled",
] as const;
export const RunStatusSchema = z.enum(RUN_STATUSES);
export type RunStatus = z.infer<typeof RunStatusSchema>;
export const TERMINAL: ReadonlySet<RunStatus> = new Set(["completed", "failed", "cancelled"]);

export const SourceSchema = z.object({ n: num, title: str, url: str });
export type Source = z.infer<typeof SourceSchema>;

export const RunViewSchema = z.object({
  run_id: str,
  status: RunStatusSchema,
  task: str,
  max_iterations: num,
  iteration: num,
  iteration_limit: num,
  final_output: str.nullable(),
  sources: z.array(SourceSchema),
  forced: z.boolean(),
  degraded: z.boolean(),
  flags: z.array(str),
  transcript: z.array(EntrySchema),
  approval: z.object({
    required: z.boolean(),
    draft: str.nullable(),
    expires_at: str.nullable(),
    revisions: num,
  }),
  memory_used: z.array(z.object({ run_id: str, task: str })),
  error: str.nullable(),
  meta: z.object({
    generated_by: str,
    models: z.record(str, str),
    prompt_version: str,
    llm_calls: num,
    cached_calls: num,
    tokens: z.object({ input: num, output: num }),
    est_cost_usd: num,
    created_at: str,
    started_at: str.nullable(),
    finished_at: str.nullable(),
    duration_ms: num.nullable(),
  }),
  sample: z.boolean(),
});
export type RunView = z.infer<typeof RunViewSchema>;

export const AcceptedSchema = z.object({
  run_id: str,
  status: str,
  status_url: str,
  events_url: str,
});
export type Accepted = z.infer<typeof AcceptedSchema>;

// ---- server info -------------------------------------------------------------------------

export const LimitsSchema = z.object({
  task_min_chars: num,
  task_max_chars: num,
  default_max_iterations: num,
  max_iterations_limit: num,
  max_parallel_delegations: num,
  approval_timeout_min: num,
  feedback_max_chars: num,
});
export type Limits = z.infer<typeof LimitsSchema>;

export const HealthSchema = z.object({
  status: str,
  service_level: z.enum(["full", "reduced", "minimal"]),
  service_reason: str.nullable(),
  retry_after_s: num.nullable(),
  llm_mode: str,
  wikipedia: str,
  models: z.object({ supervisor: str, workers: str }),
  prompt_version: str,
  usage_today: z.object({ calls: num, limit: num }),
  limits: LimitsSchema,
});
export type Health = z.infer<typeof HealthSchema>;

export const AgentSchema = z.object({
  name: str,
  title: str,
  role: z.enum(["supervisor", "worker"]),
  description: str,
});
export type Agent = z.infer<typeof AgentSchema>;

export const SampleSchema = z.object({ id: str, title: str, task: str });
export type Sample = z.infer<typeof SampleSchema>;

// ---- SSE events ----------------------------------------------------------------------------

export const EventSchemas = {
  run_started: z.object({ iteration: num, iteration_limit: num }),
  agent_started: z.object({ agent: str, iteration: num, task: str.nullable() }),
  decision: EntrySchema,
  worker_result: EntrySchema,
  notice: EntrySchema,
  feedback: EntrySchema,
  awaiting_approval: z.object({ draft: str, expires_at: str }),
  completed: z.object({ final_output: str, forced: z.boolean(), degraded: z.boolean() }),
  failed: z.object({ error: str }),
  cancelled: z.object({ reason: str }),
} as const;

export type EventType = keyof typeof EventSchemas;
export const EVENT_TYPES = Object.keys(EventSchemas) as EventType[];
export const TERMINAL_EVENTS: ReadonlySet<EventType> = new Set(["completed", "failed", "cancelled"]);

export type RunEvent = {
  [K in EventType]: { id: number; type: K; data: z.infer<(typeof EventSchemas)[K]> };
}[EventType];
