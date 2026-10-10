import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "@/lib/api";
import { ApiError, fieldLabel } from "@/lib/api";
import { health, ragRun } from "./fixtures";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  // a new Response per call: a body can be read once
  const fetchMock = vi.fn().mockImplementation(
    async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const problem = (slug: string, status: number, extra: object = {}) => ({
  type: `https://api.example/problems/${slug}`,
  title: "T",
  status,
  detail: `detail of ${slug}`,
  ...extra,
});

async function errorOf(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (err) {
    if (err instanceof ApiError) return err;
  }
  throw new Error("expected an ApiError");
}

afterEach(() => vi.unstubAllGlobals());

describe("requests", () => {
  it("starts a run with the task and settings", async () => {
    const fetchMock = respond(202, { run_id: "run_1", status: "queued", status_url: "/runs/run_1", events_url: "/runs/run_1/events" });
    const accepted = await api.startRun("A task here", { max_iterations: 3, require_approval: true, use_memory: false });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/run");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ task: "A task here", max_iterations: 3, require_approval: true, use_memory: false });
    expect(accepted.run_id).toBe("run_1");
  });

  it("reads runs, approves and rejects", async () => {
    const fetchMock = respond(200, ragRun);
    expect((await api.getRun("run_x")).run_id).toBe(ragRun.run_id);
    await api.approve("run_x");
    await api.reject("run_x", "More detail");
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "http://localhost:8000/runs/run_x",
      "http://localhost:8000/runs/run_x/approve",
      "http://localhost:8000/runs/run_x/reject",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ feedback: "More detail" });
    expect(api.eventsUrl("run_x")).toBe("http://localhost:8000/runs/run_x/events");
  });

  it("reads health, agents and samples; uses NEXT_PUBLIC_API_URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example/");
    const fetchMock = respond(200, health);
    expect((await api.health()).limits.task_max_chars).toBe(2000);
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example/health");
    respond(200, [{ name: "writer", title: "Writer", role: "worker", description: "d" }]);
    expect((await api.agents())[0].name).toBe("writer");
    respond(200, [{ id: "a", title: "A", task: "t" }]);
    expect((await api.samples())[0].id).toBe("a");
    respond(200, { ...ragRun, sample: true });
    expect((await api.sample("rag")).sample).toBe(true);
  });
});

describe("errors (RFC 9457)", () => {
  it.each([
    ["validation-error", 422, "validation"],
    ["malformed-request", 400, "validation"],
    ["input-too-large", 413, "too_large"],
    ["run-not-found", 404, "not_found"],
    ["sample-not-found", 404, "not_found"],
    ["invalid-transition", 409, "conflict"],
    ["rate-limited", 429, "rate_limited"],
    ["llm-quota-exhausted", 503, "quota"],
    ["llm-unavailable", 503, "busy"],
  ])("%s → %s", async (slug, status, kind) => {
    respond(status, problem(slug, status), { "Retry-After": "42" });
    const err = await errorOf(api.getRun("run_x"));
    expect(err.kind).toBe(kind);
    expect(err.slug).toBe(slug);
    expect(err.retryAfter).toBe(42);
  });

  it("maps field errors to labels", async () => {
    respond(422, problem("validation-error", 422, { errors: [{ pointer: "#/max_iterations", detail: "Must be between 1 and 8." }] }));
    const err = await errorOf(api.startRun("x", { max_iterations: 9, require_approval: false, use_memory: true }));
    expect(err.fieldErrors).toEqual(["Max iterations: Must be between 1 and 8."]);
    expect(fieldLabel("#/task")).toBe("Task");
    expect(fieldLabel("#/some_field")).toBe("Some field");
    expect(fieldLabel("#")).toBe("Request");
  });

  it("falls back on status codes and non-JSON bodies", async () => {
    for (const [status, kind] of [[400, "validation"], [404, "not_found"], [429, "rate_limited"], [503, "busy"], [500, "server"]] as const) {
      respond(status, "<html>proxy</html>");
      expect((await errorOf(api.health())).kind).toBe(kind);
    }
  });

  it("rejects responses that do not match the schema", async () => {
    respond(200, { run_id: 42 });
    expect((await errorOf(api.getRun("run_x"))).kind).toBe("invalid_response");
  });

  it("network failure and timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect((await errorOf(api.health())).kind).toBe("network");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("t", "TimeoutError")));
    expect((await errorOf(api.health())).kind).toBe("timeout");
  });
});
