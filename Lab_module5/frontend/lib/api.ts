/** The API client (Lab 4 pattern): fetch + Zod + ApiError mapped from RFC 9457 slugs. */
import { z } from "zod";
import {
  type Accepted,
  AcceptedSchema,
  type Agent,
  AgentSchema,
  type Health,
  HealthSchema,
  ProblemSchema,
  type RunView,
  RunViewSchema,
  type Sample,
  SampleSchema,
} from "./schemas";

export type ApiErrorKind =
  | "validation"
  | "too_large"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "quota"
  | "busy"
  | "timeout"
  | "server"
  | "network"
  | "invalid_response";

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public retryAfter?: number,
    public fieldErrors: string[] = [],
    public slug = "",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const TIMEOUT_MS = 30_000; // POST /run answers 202 at once; the work streams over SSE

export function apiUrl(): string {
  // Referenced directly so Next.js inlines the value at build time.
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

const FIELD_LABELS: Record<string, string> = {
  task: "Task",
  max_iterations: "Max iterations",
  require_approval: "Require approval",
  use_memory: "Use memory",
  feedback: "Feedback",
};

/** "#/max_iterations" → "Max iterations". */
export function fieldLabel(pointer: string): string {
  const head = pointer.replace(/^#\/?/, "").split("/").filter(Boolean)[0];
  if (!head) return "Request";
  return FIELD_LABELS[head] ?? head.charAt(0).toUpperCase() + head.slice(1).replaceAll("_", " ");
}

async function toApiError(res: Response): Promise<ApiError> {
  const retryHeader = Number(res.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retryHeader) && retryHeader > 0 ? retryHeader : undefined;
  let detail: string | undefined;
  let title: string | undefined;
  let slug = "";
  let fieldErrors: string[] = [];
  try {
    const problem = ProblemSchema.safeParse(await res.json());
    if (problem.success) {
      detail = problem.data.detail;
      title = problem.data.title;
      slug = problem.data.type?.split("/").pop() ?? "";
      fieldErrors = (problem.data.errors ?? []).map((e) => `${fieldLabel(e.pointer)}: ${e.detail}`);
    }
  } catch {
    // Not JSON (e.g. a proxy error page): fall back to the generic messages below.
  }
  const err = (kind: ApiErrorKind, message: string, fields: string[] = []) =>
    new ApiError(kind, message, retryAfter, fields, slug);

  switch (slug) {
    case "validation-error":
    case "malformed-request":
      return err("validation", detail ?? "The request is not valid.", fieldErrors);
    case "input-too-large":
      return err("too_large", detail ?? "The task is too long.");
    case "run-not-found":
      return err("not_found", "This run is no longer available. Runs are kept for 30 days.");
    case "sample-not-found":
      return err("not_found", "Sample not found.");
    case "invalid-transition":
      return err("conflict", "The run already moved on.");
    case "rate-limited":
      return err("rate_limited", "You started too many runs in a short time.");
    case "llm-quota-exhausted":
      return err("quota", "Today's free AI quota is used up. The samples still work.");
    case "llm-unavailable":
      return err("busy", "The research service is busy right now.");
  }
  if (res.status === 400 || res.status === 422) {
    return err("validation", detail ?? "The request is not valid.", fieldErrors);
  }
  if (res.status === 404) return err("not_found", "Not found.");
  if (res.status === 429) return err("rate_limited", "You started too many runs in a short time.");
  if (res.status === 503) return err("busy", "The research service is busy right now.");
  return err("server", title ?? "Something went wrong on the server. Please try again.");
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${apiUrl()}${path}`, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new ApiError("timeout", "The server took too long to answer. Please try again.");
    }
    throw new ApiError("network", "Can't reach the research service. Check your connection.");
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  const parsed = schema.safeParse(await res.json().catch(() => undefined));
  if (!parsed.success) {
    throw new ApiError("invalid_response", "Unexpected response from the server.");
  }
  return parsed.data;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const enc = encodeURIComponent;

export interface RunSettings {
  max_iterations: number;
  require_approval: boolean;
  use_memory: boolean;
}

export const health = (): Promise<Health> => request("/health", HealthSchema);
export const agents = (): Promise<Agent[]> => request("/agents", z.array(AgentSchema));
export const samples = (): Promise<Sample[]> => request("/samples", z.array(SampleSchema));
export const sample = (id: string): Promise<RunView> =>
  request(`/samples/${enc(id)}`, RunViewSchema);

/** Starts a run (202). The caller follows it with getRun() and the events stream. */
export const startRun = (task: string, settings: RunSettings): Promise<Accepted> =>
  request("/run", AcceptedSchema, post({ task, ...settings }));
export const getRun = (id: string): Promise<RunView> => request(`/runs/${enc(id)}`, RunViewSchema);
export const approve = (id: string): Promise<RunView> =>
  request(`/runs/${enc(id)}/approve`, RunViewSchema, post());
export const reject = (id: string, feedback: string | null): Promise<RunView> =>
  request(`/runs/${enc(id)}/reject`, RunViewSchema, post({ feedback }));

export const eventsUrl = (id: string): string => `${apiUrl()}/runs/${enc(id)}/events`;
