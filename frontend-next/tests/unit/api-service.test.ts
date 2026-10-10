import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "@/api/client";
import {
  ApiOperationsService,
  type EventStream,
} from "@/services/api-operations";
import { controls } from "@/domain/case-view";
import {
  CASE_A,
  CASE_B,
  CASE_C,
  auditRows,
  detailA,
  detailB,
  exploreItems,
  page,
  pipelineEvents,
  queueRows,
  schema,
  session,
  workerStatus,
} from "../fixtures/backend";

type Call = { method: string; path: string; query: URLSearchParams; body: unknown; token: string | null };
type Handler = (call: Call) => unknown;
class HttpError {
  constructor(
    public status: number,
    public detail: string,
  ) {}
}

/** A stand-in for the backend's HTTP surface, used only to drive the service in tests. */
function backend(overrides: Record<string, Handler> = {}) {
  const calls: Call[] = [];
  const routes: Record<string, Handler> = {
    "GET /operations/session": () => session,
    "GET /worker/status": () => workerStatus,
    "GET /cases/queue": () => page(queueRows),
    "GET /explore": () => page(exploreItems),
    "GET /audit": () => page(auditRows),
    "GET /schema": () => schema,
    [`GET /cases/${CASE_A}`]: () => detailA(),
    [`GET /cases/${CASE_B}`]: () => detailB(),
    ...overrides,
  };
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://127.0.0.1:8000");
    const headers = new Headers(init?.headers);
    const call: Call = {
      method: init?.method ?? "GET",
      path: url.pathname,
      query: url.searchParams,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      token: headers.get("X-Operations-Token"),
    };
    calls.push(call);
    const handler = routes[`${call.method} ${call.path}`];
    try {
      if (!handler) throw new HttpError(404, "Operational case or shipment not found");
      return new Response(JSON.stringify(handler(call)), { status: 200 });
    } catch (error) {
      if (error instanceof HttpError)
        return new Response(JSON.stringify({ detail: error.detail }), { status: error.status });
      throw error;
    }
  }) as typeof fetch;
  class Stream implements EventStream {
    listeners = new Map<string, (event: MessageEvent) => void>();
    onerror: ((event: Event) => void) | null = null;
    closed = false;
    constructor(public url: string) {}
    addEventListener(type: string, listener: (event: MessageEvent) => void) {
      this.listeners.set(type, listener);
    }
    close() {
      this.closed = true;
    }
    emit(type: string, data: unknown) {
      this.listeners.get(type)?.({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
  const streams: Stream[] = [];
  const service = new ApiOperationsService({
    client: new ApiClient({ origin: "http://127.0.0.1:8000", fetch: fetcher }),
    eventSource: (url) => {
      const stream = new Stream(url);
      streams.push(stream);
      return stream;
    },
    now: () => "2026-10-10T10:00:00.000Z",
  });
  const posts = () => calls.filter((call) => call.method === "POST");
  return { service, calls, posts, streams, routes };
}
const find = (service: ApiOperationsService, id: string) =>
  service.getSnapshot().cases.find((c) => c.id === id)!;

afterEach(() => vi.useRealTimers());

describe("ApiOperationsService reads", () => {
  it("shows the backend's queue, newest first, and loads resolved outcomes for the Resolved rail", async () => {
    const { service } = backend();
    await service.refresh();
    const snapshot = service.getSnapshot();
    expect(snapshot.connection).toMatchObject({
      state: "online",
      database: "shipments-v2-demo-live",
      asOf: "2026-09-03T14:00:00+00:00",
      queue: { total: 3, loaded: 3, truncated: false },
    });
    expect(snapshot.cases.map((c) => c.id)).toEqual([CASE_C, CASE_A, CASE_B]);
    expect(snapshot.automatic).toBe(false);
    // Only the resolved case's detail was needed: its independently verified outcome.
    expect(find(service, CASE_B).outcome?.successful).toBe(true);
    expect(find(service, CASE_A).backend?.detailLoaded).toBe(false);
    expect(service.catalog().source).toBe("backend");
    expect(service.catalog().causes).toEqual([{ value: "DELAYED_SYNC", label: "Delayed sync" }]);
    expect(service.catalog().cities).toContain("Dammam");
  });

  it("follows cursors and says when the backend holds more than was loaded", async () => {
    let served = 0;
    const { service } = backend({
      "GET /cases/queue": (call) => {
        served += 1;
        expect(call.query.get("scope")).toBe("all");
        expect(call.query.get("limit")).toBe("100");
        return {
          ...page([{ ...queueRows[2], case_id: `SYN-CASE-P${served}` }], `cursor-${served}`),
          filtered_total: 5000,
        };
      },
    });
    await service.refresh();
    const queue = service.getSnapshot().connection?.queue;
    expect(served).toBe(10);
    expect(queue).toEqual({ total: 5000, loaded: 10, truncated: true });
  });

  it("shows nothing rather than stand-in data when the backend is unreachable", async () => {
    const { service } = backend({
      "GET /worker/status": () => {
        throw new HttpError(503, "The validated V2 operations database is unavailable");
      },
    });
    await service.refresh();
    const snapshot = service.getSnapshot();
    expect(snapshot.cases).toEqual([]);
    expect(snapshot.events).toEqual([]);
    expect(snapshot.connection?.state).toBe("offline");
    expect(snapshot.connection?.error).toMatch(/V2 operations database is unavailable/);
  });

  it("keeps the last read, marked interrupted, when the backend drops out later", async () => {
    const world = backend();
    await world.service.refresh();
    world.routes["GET /worker/status"] = () => {
      throw new HttpError(503, "The V2 graph is unavailable");
    };
    await world.service.refresh();
    const snapshot = world.service.getSnapshot();
    expect(snapshot.connection?.state).toBe("degraded");
    expect(snapshot.connection?.lastSyncAt).toBe("2026-10-10T10:00:00.000Z");
    expect(snapshot.cases).toHaveLength(3);
  });

  it("keeps unchanged cases identical across polls so maps and graphs are not rebuilt", async () => {
    const { service } = backend();
    await service.refresh();
    const first = service.getSnapshot();
    await service.refresh();
    const second = service.getSnapshot();
    expect(second.cases).toBe(first.cases);
    expect(second.revision).toBeGreaterThan(first.revision);
  });

  it("loads the audit ledger as backend records and derives the decision history from it", async () => {
    const { service } = backend();
    await service.refresh();
    await service.loadAudit();
    const snapshot = service.getSnapshot();
    expect(snapshot.events).toHaveLength(4);
    expect(snapshot.events.every((event) => event.simulated === false)).toBe(true);
    expect(snapshot.events[0].id).toBe("SYN-AUD-4");
    expect(snapshot.decisions).toHaveLength(1);
    expect(snapshot.decisions[0]).toMatchObject({ caseId: CASE_B, verdict: "approved", reason: "" });
    expect(snapshot.connection?.audit).toMatchObject({ total: 4, loaded: 4, truncated: false, loading: false });
  });

  it("lists a decision once even though the case detail and the audit ledger both record it", async () => {
    const { service } = backend({
      [`GET /cases/${CASE_B}`]: () => ({
        ...detailB(),
        // The same approval as the audit record, on the dataset clock.
        decisions: [{ decision: "approve", occurred_at: "2026-09-03T13:00:00+00:00", actor_id: "SYN-OPERATOR-LOCAL" }],
      }),
    });
    await service.refresh();
    expect(service.getSnapshot().decisions).toHaveLength(1);
    await service.loadAudit();
    const decisions = service.getSnapshot().decisions;
    expect(decisions).toHaveLength(1);
    expect(decisions[0].timestamp).toBe("2026-10-09T10:05:00+00:00");
  });

  it("reads the live schema from the backend", async () => {
    const { service } = backend();
    const result = await service.schema();
    expect(result.nodes.map((n) => n.label)).toEqual(["Shipment", "Package", "CustodyEvent"]);
    expect(result.relationships).toHaveLength(2);
  });
});

describe("ApiOperationsService operator requests", () => {
  it("sends an approval with the loaded version, a fresh idempotency key and the session token, and nothing else", async () => {
    const world = backend({
      [`POST /cases/${CASE_A}/decision`]: () => ({
        case_id: CASE_A,
        workflow_state: "AWAITING_OUTCOME",
        state_version: 9,
      }),
    });
    await world.service.refresh();
    await world.service.decide(CASE_A, "approved", "operator typed a reason");
    const [post] = world.posts();
    expect(post.path).toBe(`/cases/${CASE_A}/decision`);
    expect(post.token).toBe(session.token);
    const body = post.body as Record<string, unknown>;
    // The backend forbids extra fields and does not store reasons; none is sent.
    expect(Object.keys(body).sort()).toEqual(["decision", "expected_version", "idempotency_key"]);
    expect(body.decision).toBe("approve");
    expect(body.expected_version).toBe(7);
    expect(String(body.idempotency_key)).toMatch(/^approve_[A-Za-z0-9]{8,}$/);
  });

  it("does not send a decision the backend does not allow for the case's state", async () => {
    const world = backend({
      [`GET /cases/${CASE_A}`]: () =>
        detailA({
          recommendation: {
            ...detailA().recommendation!,
            approvable: false,
            approval_rule: "AUTH-20-approval-context-stale",
            approval_reason: "The basis changed; the case is re-investigated before anything is approved.",
          },
        }),
    });
    await world.service.refresh();
    await expect(world.service.decide(CASE_A, "approved", "")).rejects.toThrow(/basis changed/);
    expect(world.posts()).toHaveLength(0);
  });

  it("reloads the authoritative case when the backend refuses or the version is stale", async () => {
    let version = 7;
    const world = backend({
      [`GET /cases/${CASE_A}`]: () => detailA({ state_version: version }),
      [`POST /cases/${CASE_A}/decision`]: () => {
        version = 8;
        throw new HttpError(409, "Case changed; reload its authoritative version");
      },
    });
    await world.service.refresh();
    await expect(world.service.decide(CASE_A, "rejected", "")).rejects.toThrow(
      /Case changed; reload its authoritative version The case was reloaded\./,
    );
    expect(find(world.service, CASE_A).backend?.stateVersion).toBe(8);
    // Nothing was approved, executed or resolved in the browser.
    expect(find(world.service, CASE_A).status).toBe("human_review");
  });

  it("asks the verifier to check, with no way to declare success", async () => {
    const world = backend({
      [`GET /cases/${CASE_A}`]: () =>
        detailA({
          workflow_state: "AWAITING_OUTCOME",
          executions: [{ receipt_ref: "SYN-RCPT-9", status: "ACKNOWLEDGED", current_cycle: true }],
        }),
      [`POST /cases/${CASE_A}/outcomes`]: () => ({ case_id: CASE_A, workflow_state: "AWAITING_OUTCOME", verified: false }),
    });
    await world.service.refresh();
    await world.service.verify(CASE_A);
    const body = world.posts()[0].body as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(["expected_version", "idempotency_key"]);
    // The verifier found nothing: the case is still awaiting its outcome.
    expect(find(world.service, CASE_A).status).toBe("verifying");
    expect(find(world.service, CASE_A).outcome).toBeUndefined();
  });

  it("starts and pauses the backend worker and reflects only what the backend then reports", async () => {
    const world = backend({
      "POST /worker/start": () => ({}),
    });
    await world.service.refresh();
    await world.service.setAutomatic(true);
    expect(world.posts()[0].path).toBe("/worker/start");
    // The backend still reports "paused" here, so the switch stays off.
    expect(world.service.getSnapshot().automatic).toBe(false);
    world.routes["GET /worker/status"] = () => ({
      ...workerStatus,
      worker: { ...workerStatus.worker, state: "running" },
    });
    await world.service.refresh();
    expect(world.service.getSnapshot().automatic).toBe(true);
  });

  it("refuses to start an investigation the lifecycle does not allow, and has no local simulation", async () => {
    const world = backend();
    await world.service.refresh();
    await expect(world.service.investigate(CASE_A)).rejects.toThrow(/only starts an investigation for a queued case/);
    expect(world.posts()).toHaveLength(0);
    const before = world.service.getSnapshot();
    world.service.tick();
    expect(world.service.getSnapshot()).toBe(before);
    expect(() => world.service.addCase()).toThrow(/opened by the backend monitor/);
    expect(() => world.service.reset()).toThrow(/cannot be reset/);
    expect(world.service.answer()).toBe("");
  });

  it("retries once with a fresh session when the backend restarted and rotated its token", async () => {
    let tokens = 0;
    const world = backend({
      "GET /operations/session": () => ({ ...session, token: `token-${(tokens += 1)}-abcdefgh` }),
      [`POST /cases/${CASE_A}/decision`]: (call) => {
        if (call.token !== "token-2-abcdefgh") throw new HttpError(403, "A local operations session is required");
        return { case_id: CASE_A, workflow_state: "ESCALATED", state_version: 8 };
      },
    });
    await world.service.refresh();
    await world.service.decide(CASE_A, "escalated", "");
    expect(world.posts().map((call) => call.token)).toEqual(["token-1-abcdefgh", "token-2-abcdefgh"]);
  });
});

describe("ApiOperationsService live pipeline", () => {
  it("loads a watched case's evidence and follows its recorded stages as they stream in", async () => {
    const world = backend({
      [`GET /cases/${CASE_C}`]: () =>
        detailA({
          case_id: CASE_C,
          workflow_state: "OPEN",
          state_version: 1,
          run: null,
          pipeline: { events: [], status: "QUEUED" },
          recommendation: null,
          diagnosis: { ...detailA().diagnosis!, available: false, reason: "not_investigated" },
        }),
    });
    await world.service.refresh();
    const unwatch = world.service.watchCase(CASE_C);
    await vi.waitFor(() => expect(find(world.service, CASE_C).backend?.detailLoaded).toBe(true));
    expect(world.streams).toHaveLength(1);
    expect(world.streams[0].url).toBe(`http://127.0.0.1:8000/cases/${CASE_C}/events`);
    expect(find(world.service, CASE_C).run).toBeUndefined();
    expect(controls(find(world.service, CASE_C)).investigate).toBe(true);

    world.streams[0].emit("pipeline", {
      workflow_state: "INVESTIGATING",
      state_version: 2,
      run_id: "SYN-RUN-7",
      status: "RUNNING",
      events: pipelineEvents.slice(0, 3),
    });
    const running = find(world.service, CASE_C);
    expect(running.status).toBe("investigating");
    expect(running.run?.stage).toBe(2);
    expect(running.backend?.stageDetail[2]).toMatch(/not reconciled at session end/);

    unwatch();
    expect(world.streams[0].closed).toBe(true);
  });

  it("reconnects a dropped stream with backoff and replaces, never replays, the state", async () => {
    vi.useFakeTimers();
    const world = backend();
    world.service.start();
    await vi.advanceTimersByTimeAsync(0);
    world.service.watchCase(CASE_A);
    await vi.advanceTimersByTimeAsync(0);
    expect(world.streams).toHaveLength(1);
    world.streams[0].onerror?.({} as Event);
    expect(world.streams[0].closed).toBe(true);
    await vi.advanceTimersByTimeAsync(999);
    expect(world.streams).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2);
    expect(world.streams).toHaveLength(2);
    world.streams[1].emit("unavailable", { error: "pipeline_unavailable" });
    await vi.advanceTimersByTimeAsync(2001);
    expect(world.streams).toHaveLength(3);
    world.service.stop();
    expect(world.streams[2].closed).toBe(true);
  });

  it("reports a case the backend does not have instead of showing an empty investigation", async () => {
    const world = backend();
    await world.service.refresh();
    world.service.watchCase("SYN-CASE-NOPE");
    await vi.waitFor(() =>
      expect(find(world.service, "SYN-CASE-NOPE").backend?.detailError).toMatch(/not found/),
    );
    expect(find(world.service, "SYN-CASE-NOPE").evidence).toEqual([]);
  });
});
