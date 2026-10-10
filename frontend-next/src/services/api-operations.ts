import { ApiClient, ApiError, idempotencyKey } from "@/api/client";
import type {
  ApiAuditEvent,
  ApiCaseDetail,
  ApiDecisionResult,
  ApiExploreItem,
  ApiPage,
  ApiPipelineState,
  ApiQueueCase,
  ApiSchema,
  ApiSession,
  ApiWorkerStatus,
} from "@/api/contracts";
import {
  DECISION_BY_VERDICT,
  applyDetail,
  applyPipeline,
  auditEvent,
  caseFromQueue,
  decisionFromAudit,
  facilitiesOf,
  humanize,
  placeholderCase,
  verdictOf,
} from "@/api/adapters";
import { cityLocations, moreCityLocations } from "@/domain/geo";
import type {
  AuthorityDecision,
  BackendConnection,
  CaseQueue,
  Facility,
  InvestigationStageEvent,
  OperationalCase,
  OperationsCatalog,
  OperationsService,
} from "@/domain/types";

/** The part of EventSource this service uses (injectable for tests). */
export interface EventStream {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
  onerror: ((event: Event) => void) | null;
}
export interface ApiOperationsOptions {
  client?: ApiClient;
  pollMs?: number;
  eventSource?: (url: string) => EventStream;
  now?: () => string;
}

const PAGE_LIMIT = 100;
/** Bounded reads: the screens say so when the backend holds more than was loaded. */
const MAX_QUEUE_PAGES = 10;
const MAX_AUDIT_PAGES = 30;
const RESOLVED_DETAILS = 30;
const OPERATIONAL: Record<string, string> = {
  ON_TIME: "في الموعد",
  NEEDS_ATTENTION: "تحتاج انتباهاً",
  SLA_RISK: "خطر على الالتزام",
  CRITICAL: "حرجة",
  UNRECONCILED_CUSTODY: "حيازة غير مسوّاة",
  DELIVERY_DISPUTE: "تسليم محل نزاع",
  ADDRESS_CONFLICT: "تعارض في العنوان",
  RECIPIENT_UNAVAILABLE: "المستلم غير متاح",
  HUB_DELAY: "تأخر في المركز",
  RESOLVED: "تم الحل",
};

function message(error: unknown) {
  return error instanceof Error ? error.message : "The request failed.";
}

/**
 * The operations queue as the Suhail backend serves it. The backend is the only source of
 * truth: this service reads, relays operator requests, and re-reads. It runs no timers that
 * advance a case, invents no events, and never marks anything executed, verified or resolved.
 */
export class ApiOperationsService implements OperationsService {
  private client: ApiClient;
  private pollMs: number;
  private openStream: (url: string) => EventStream;
  private now: () => string;
  private listeners = new Set<() => void>();
  private cases = new Map<string, OperationalCase>();
  private order: string[] = [];
  private explore = new Map<string, ApiExploreItem>();
  private audit = new Map<string, InvestigationStageEvent>();
  private auditDecisions = new Map<string, AuthorityDecision>();
  private detailDecisions = new Map<string, AuthorityDecision>();
  private facilities = new Map<string, Facility>();
  /** What each case was last built from, so unchanged cases keep their identity across polls. */
  private rowSignature = new Map<string, string>();
  private detailSignature = new Map<string, string>();
  private dirty = { cases: true, events: true, decisions: true };
  private cities: string[] = [];
  private watchers = new Map<
    string,
    { count: number; stream?: EventStream; retry?: ReturnType<typeof setTimeout>; attempt: number }
  >();
  private details = new Map<string, Promise<void>>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private refreshing: Promise<void> | null = null;
  private auditLoading: Promise<void> | null = null;
  private auditSince: string | null = null;
  private started = false;
  private polls = 0;
  private automatic = false;
  private connection: BackendConnection = {
    state: "connecting",
    synthetic: true,
    controls: "unknown",
  };
  private snapshot: CaseQueue;

  constructor(options: ApiOperationsOptions = {}) {
    this.client = options.client ?? new ApiClient();
    this.pollMs = options.pollMs ?? 5000;
    this.openStream =
      options.eventSource ?? ((url) => new EventSource(url) as EventStream);
    this.now = options.now ?? (() => new Date().toISOString());
    this.snapshot = this.build(0);
  }

  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Begin reading the backend. Safe to call more than once. */
  start() {
    if (this.started) return;
    this.started = true;
    void this.loadSession();
    void this.refresh();
    this.timer = setInterval(() => {
      if (typeof document === "undefined" || !document.hidden)
        void this.refresh();
    }, this.pollMs);
    if (typeof document !== "undefined")
      document.addEventListener("visibilitychange", this.onVisible);
  }
  stop() {
    this.started = false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (typeof document !== "undefined")
      document.removeEventListener("visibilitychange", this.onVisible);
    for (const watcher of this.watchers.values()) {
      watcher.stream?.close();
      if (watcher.retry) clearTimeout(watcher.retry);
      watcher.stream = undefined;
    }
  }
  private onVisible = () => {
    if (!document.hidden) void this.refresh();
  };

  private build(revision: number): CaseQueue {
    // Lists keep their identity while their content is unchanged, so maps and graphs
    // are not rebuilt (and the operator's pan and zoom are not reset) on every poll.
    const last = this.snapshot as CaseQueue | undefined;
    const cases =
      last && !this.dirty.cases
        ? last.cases
        : this.order
            .map((id) => this.cases.get(id))
            .filter((c): c is OperationalCase => !!c);
    const events =
      last && !this.dirty.events
        ? last.events
        : [...this.audit.values()].sort(
            (a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp),
          );
    const decisions =
      last && !this.dirty.decisions
        ? last.decisions
        : // The audit ledger is the decision history once it is loaded. Case details record the
          // same decisions on the dataset clock, so the two are never merged (no double rows).
          [
            ...(this.audit.size
              ? this.auditDecisions
              : this.detailDecisions
            ).values(),
          ].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
    this.dirty = { cases: false, events: false, decisions: false };
    return {
      cases,
      automatic: this.automatic,
      events,
      decisions,
      revision,
      version: 1,
      connection: this.connection,
    };
  }
  private commit() {
    this.snapshot = this.build(this.snapshot.revision + 1);
    this.listeners.forEach((listener) => listener());
  }
  private connect(change: Partial<BackendConnection>) {
    this.connection = { ...this.connection, ...change };
  }
  private put(c: OperationalCase) {
    if (!this.cases.has(c.id)) this.order.push(c.id);
    this.cases.set(c.id, c);
    this.dirty.cases = true;
  }

  private async loadSession() {
    try {
      const session: ApiSession = await this.client.getSession();
      this.connect({
        operator: {
          actorId: session.actor_id,
          role: session.role,
          mode: session.mode,
        },
        controls: "available",
      });
    } catch (error) {
      // 403: the backend only grants its local operations session to a loopback, same-origin page.
      this.connect({
        controls:
          error instanceof ApiError && error.status === 403
            ? "unavailable"
            : "unknown",
      });
    }
    this.commit();
  }

  private async pages<T>(
    path: string,
    query: Record<string, string | number | null | undefined>,
    maxPages: number,
  ) {
    const items: T[] = [];
    let cursor: string | null = null;
    let first: ApiPage<T> | null = null;
    let truncated = false;
    for (let page = 0; page < maxPages; page += 1) {
      const result: ApiPage<T> = await this.client.get<ApiPage<T>>(path, {
        ...query,
        limit: PAGE_LIMIT,
        cursor,
      });
      first ??= result;
      items.push(...result.items);
      cursor = result.next_cursor;
      if (!cursor) break;
      if (page === maxPages - 1) truncated = true;
    }
    return { items, first: first!, truncated };
  }

  /** After an operator request: a read that started before it must not be mistaken for the result. */
  private async refreshAfterChange() {
    if (this.refreshing) await this.refreshing.catch(() => undefined);
    await this.refresh();
  }
  refresh = (): Promise<void> => {
    this.refreshing ??= this.read().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  };
  private async read() {
    try {
      const status = await this.client.get<ApiWorkerStatus>("/worker/status");
      const queue = await this.pages<ApiQueueCase>(
        "/cases/queue",
        { scope: "all" },
        MAX_QUEUE_PAGES,
      );
      // Origin cities and coordinates come from Explore; re-read occasionally, not every poll.
      if (this.polls % 6 === 0) {
        try {
          const explore = await this.pages<ApiExploreItem>(
            "/explore",
            { filter: "all" },
            MAX_QUEUE_PAGES,
          );
          this.explore = new Map(
            explore.items
              .filter((item) => item.case_id)
              .map((item) => [item.case_id!, item]),
          );
        } catch {
          /* Explore enrichment is optional; the queue stays authoritative. */
        }
      }
      this.polls += 1;
      const present = new Set<string>();
      const stale: string[] = [];
      for (const row of queue.items) {
        present.add(row.case_id);
        const previous = this.cases.get(row.case_id);
        const joined = this.explore.get(row.case_id);
        const signature = JSON.stringify([row, joined?.origin_city ?? null]);
        if (previous && this.rowSignature.get(row.case_id) === signature)
          continue;
        this.rowSignature.set(row.case_id, signature);
        const next = caseFromQueue(row, previous, joined);
        this.put(next);
        if (previous?.backend?.detailLoaded && !next.backend!.detailLoaded)
          stale.push(row.case_id);
      }
      // A case the backend no longer lists is dropped, unless a screen is holding it open.
      this.order = this.order.filter((id) => {
        if (present.has(id) || this.watchers.has(id)) return true;
        this.cases.delete(id);
        this.rowSignature.delete(id);
        this.detailSignature.delete(id);
        this.dirty.cases = true;
        return false;
      });
      const before = this.order.join("|");
      // The ledger lists oldest first; the screens show newest first.
      this.order.sort(
        (a, b) =>
          Date.parse(this.cases.get(b)?.openedAt ?? "") -
          Date.parse(this.cases.get(a)?.openedAt ?? ""),
      );
      if (this.order.join("|") !== before) this.dirty.cases = true;
      this.cities =
        queue.first.metadata?.filter_choices?.city ??
        [...new Set(queue.items.map((row) => row.city).filter(Boolean))].map(
          String,
        );
      this.automatic = status.worker.state === "running";
      this.connect({
        state: "online",
        error: undefined,
        lastSyncAt: this.now(),
        asOf: status.as_of,
        database: status.database,
        synthetic: status.synthetic !== false,
        worker: {
          state: status.worker.state,
          activeCaseId: status.worker.active_case_id ?? null,
          processedCount: status.worker.processed_count ?? 0,
          lastCaseId: status.worker.last_case_id ?? null,
        },
        queue: {
          total: queue.first.filtered_total,
          loaded: queue.items.length,
          truncated: queue.truncated,
        },
      });
      this.commit();
      // Evidence is loaded for what a screen needs: watched cases, changed cases, and the
      // resolved cases whose verified outcome the Resolved rail shows.
      const resolved = queue.items
        .filter((row) => row.workflow_state === "RESOLVED")
        .slice(-RESOLVED_DETAILS)
        .map((row) => row.case_id);
      const wanted = new Set([...stale, ...this.watchers.keys(), ...resolved]);
      // The case the worker holds is re-read every poll so its recorded stages stay current.
      const active = status.worker.active_case_id;
      await Promise.all([
        ...[...wanted]
          .filter((id) => id !== active && !this.cases.get(id)?.backend?.detailLoaded)
          .map((id) => this.loadDetail(id).catch(() => undefined)),
        ...(active && this.cases.has(active)
          ? [this.loadDetail(active, true).catch(() => undefined)]
          : []),
      ]);
      if (this.audit.size) void this.loadAudit();
    } catch (error) {
      this.connect({
        state: this.connection.lastSyncAt ? "degraded" : "offline",
        error: message(error),
      });
      this.commit();
    }
  }

  private loadDetail(id: string, force = false): Promise<void> {
    const running = this.details.get(id);
    if (running && !force) return running;
    const load = this.client
      .get<ApiCaseDetail>(`/cases/${encodeURIComponent(id)}`)
      .then((detail) => {
        const base = this.cases.get(id) ?? placeholderCase(id);
        // An unchanged detail (the worker's case is re-read every poll) changes nothing.
        const signature = JSON.stringify(detail);
        if (
          base.backend?.detailLoaded &&
          this.detailSignature.get(id) === signature
        )
          return;
        this.detailSignature.set(id, signature);
        const next = applyDetail(base, detail);
        this.put(next);
        for (const facility of facilitiesOf(detail))
          this.facilities.set(facility.id, facility);
        for (const record of detail.decisions ?? []) {
          const verdict = verdictOf(record.decision);
          if (!verdict || !record.occurred_at) continue;
          this.dirty.decisions = true;
          this.detailDecisions.set(`${id}|${record.occurred_at}|${verdict}`, {
            caseId: id,
            action: next.recommendation.available
              ? next.recommendation.title
              : humanize(record.decision),
            verdict,
            actor: record.actor_id ?? "",
            timestamp: record.occurred_at,
            reason: "",
          });
        }
        this.commit();
      })
      .catch((error) => {
        const base = this.cases.get(id) ?? placeholderCase(id);
        this.put({
          ...base,
          backend: { ...base.backend!, detailError: message(error) },
        });
        this.commit();
        throw error;
      })
      .finally(() => {
        if (this.details.get(id) === load) this.details.delete(id);
      });
    this.details.set(id, load);
    return load;
  }

  /** Hold a case open: load its evidence and follow its recorded pipeline events live. */
  watchCase = (id: string) => {
    const watcher = this.watchers.get(id) ?? { count: 0, attempt: 0 };
    watcher.count += 1;
    this.watchers.set(id, watcher);
    if (!this.cases.has(id)) {
      this.put(placeholderCase(id));
      this.commit();
    }
    void this.loadDetail(id).catch(() => undefined);
    this.follow(id);
    return () => {
      const current = this.watchers.get(id);
      if (!current) return;
      current.count -= 1;
      if (current.count > 0) return;
      current.stream?.close();
      if (current.retry) clearTimeout(current.retry);
      this.watchers.delete(id);
    };
  };
  private follow(id: string) {
    const watcher = this.watchers.get(id);
    // Only cases a screen holds open are streamed; the active case is otherwise polled.
    if (!watcher || watcher.stream) return;
    let stream: EventStream;
    try {
      stream = this.openStream(
        this.client.url(`/cases/${encodeURIComponent(id)}/events`),
      );
    } catch {
      return;
    }
    watcher.stream = stream;
    const reconnect = () => {
      stream.close();
      if (watcher.stream === stream) watcher.stream = undefined;
      if (!this.watchers.has(id) || !this.started) return;
      // Backoff: 1s, 2s, 4s ... capped at 15s. The next snapshot replaces, never replays.
      const delay = Math.min(15000, 1000 * 2 ** Math.min(watcher.attempt, 4));
      watcher.attempt += 1;
      watcher.retry = setTimeout(() => this.follow(id), delay);
    };
    stream.addEventListener("pipeline", (event) => {
      watcher.attempt = 0;
      let state: ApiPipelineState;
      try {
        state = JSON.parse(event.data) as ApiPipelineState;
      } catch {
        return;
      }
      const current = this.cases.get(id);
      if (!current) return;
      const changed =
        current.backend?.stateVersion !== state.state_version ||
        current.backend?.workflowState !== state.workflow_state;
      this.put(applyPipeline(current, state));
      this.commit();
      // The stream carries stages only; a state change means new evidence, review or outcome.
      if (changed) void this.loadDetail(id, true).catch(() => undefined);
    });
    stream.addEventListener("unavailable", reconnect);
    stream.onerror = reconnect;
  }

  loadCases = async (ids: string[]) => {
    await Promise.all(
      ids
        .filter((id) => !this.cases.get(id)?.backend?.detailLoaded)
        .map((id) => this.loadDetail(id).catch(() => undefined)),
    );
  };

  private caseFor(id: string) {
    const c = this.cases.get(id);
    if (!c?.backend) throw new Error("This case is not loaded from the backend.");
    return c;
  }
  private async command<T>(id: string, run: (c: OperationalCase) => Promise<T>) {
    if (!this.cases.get(id)?.backend?.detailLoaded) await this.loadDetail(id);
    const c = this.caseFor(id);
    try {
      const result = await run(c);
      await Promise.all([
        this.loadDetail(id, true).catch(() => undefined),
        this.refreshAfterChange(),
      ]);
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.conflict) {
        // The case moved on, or the backend refused: show the authoritative state again.
        await this.loadDetail(id, true).catch(() => undefined);
        void this.refresh();
        throw new Error(`${error.message} The case was reloaded.`);
      }
      throw error;
    }
  }

  async setAutomatic(enabled: boolean) {
    await this.client.post(enabled ? "/worker/start" : "/worker/pause");
    await this.refreshAfterChange();
  }
  /**
   * Ask the backend to investigate now. The request runs the real investigation and can take
   * minutes; progress arrives through the pipeline stream, so this returns once it is under way.
   */
  async investigate(id: string) {
    const c = this.caseFor(id);
    if (!c.backend!.allowed.investigate)
      throw new Error(
        `This case is ${humanize(c.backend!.workflowState).toLowerCase()}; the backend only starts an investigation for a queued case.`,
      );
    const request = this.client
      .post(`/cases/${encodeURIComponent(id)}/investigate`, undefined, 900000)
      .then(() => undefined);
    const settled = request.then(
      () => "done" as const,
      (error: unknown) => {
        throw error;
      },
    );
    const started = new Promise<"started">((resolve) =>
      setTimeout(() => resolve("started"), 1500),
    );
    const outcome = await Promise.race([settled, started]);
    if (outcome === "started")
      request
        .catch((error: unknown) => {
          this.connect({ error: `Investigation request: ${message(error)}` });
          this.commit();
        })
        .finally(() => {
          void this.loadDetail(id, true).catch(() => undefined);
          void this.refresh();
        });
    else await this.loadDetail(id, true).catch(() => undefined);
    void this.refresh();
  }
  async decide(
    id: string,
    verdict: AuthorityDecision["verdict"],
    reason = "",
  ) {
    // The backend's decision contract has no reason field yet and rejects extra fields, so a
    // reason is never sent, and it is not kept in the browser as if it had been audited.
    void reason;
    const decision = DECISION_BY_VERDICT[verdict];
    if (!decision) throw new Error("This decision is not available here.");
    await this.command(id, (c) => {
      const allowed = c.backend!.allowed;
      if (
        (decision === "approve" && !allowed.approve) ||
        (decision === "reject" && !allowed.reject) ||
        (decision === "escalate" && !allowed.escalate)
      )
        throw new Error(
          decision === "approve" && c.backend!.approvalReason
            ? c.backend!.approvalReason
            : "The backend does not accept this decision for the case's current state.",
        );
      return this.client.post<ApiDecisionResult>(
        `/cases/${encodeURIComponent(id)}/decision`,
        {
          decision,
          expected_version: c.backend!.stateVersion,
          idempotency_key: idempotencyKey(decision),
        },
      );
    });
  }
  /** Ask the independent verifier to check now. Nobody, including this page, can declare success. */
  async verify(id: string) {
    await this.command(id, (c) =>
      this.client.post(`/cases/${encodeURIComponent(id)}/outcomes`, {
        expected_version: c.backend!.stateVersion,
        idempotency_key: idempotencyKey("verify"),
      }),
    );
  }

  /** The audit ledger, oldest first from the backend, loaded in bounded pages and then incrementally. */
  loadAudit = (): Promise<void> => {
    this.auditLoading ??= this.readAudit().finally(() => {
      this.auditLoading = null;
    });
    return this.auditLoading;
  };
  private async readAudit() {
    this.connect({
      audit: {
        total: this.connection.audit?.total ?? 0,
        loaded: this.audit.size,
        truncated: this.connection.audit?.truncated ?? false,
        loading: true,
      },
    });
    this.commit();
    try {
      const result = await this.pages<ApiAuditEvent>(
        "/audit",
        this.auditSince ? { from: this.auditSince } : {},
        MAX_AUDIT_PAGES,
      );
      for (const row of result.items) {
        if (this.audit.has(row.id)) continue;
        this.dirty.events = true;
        this.audit.set(row.id, auditEvent(row));
        const c = row.case_id ? this.cases.get(row.case_id) : undefined;
        const decision = decisionFromAudit(
          row,
          c?.recommendation.available ? c.recommendation.title : "",
        );
        if (decision) this.dirty.decisions = true;
        if (decision)
          this.auditDecisions.set(
            `${decision.caseId}|${decision.timestamp}|${decision.verdict}`,
            decision,
          );
        if (row.scenario_time && (!this.auditSince || row.scenario_time > this.auditSince))
          this.auditSince = row.scenario_time;
      }
      const first = !this.connection.audit?.total;
      this.connect({
        audit: {
          total: first
            ? result.first.filtered_total
            : Math.max(this.connection.audit?.total ?? 0, this.audit.size),
          loaded: this.audit.size,
          truncated: first ? result.truncated : (this.connection.audit?.truncated ?? false),
          loading: false,
        },
      });
    } catch (error) {
      this.connect({
        error: `Audit: ${message(error)}`,
        audit: {
          total: this.connection.audit?.total ?? 0,
          loaded: this.audit.size,
          truncated: this.connection.audit?.truncated ?? false,
          loading: false,
        },
      });
    }
    this.commit();
  }

  async schema() {
    const result = await this.client.get<ApiSchema>("/schema");
    return {
      nodes: result.nodes.map((node) => ({ id: node.id, label: node.caption })),
      relationships: result.relationships,
    };
  }

  catalog(): OperationsCatalog {
    const cases = [...this.cases.values()];
    const causes = [
      ...new Set(cases.flatMap((c) => c.backend?.causeCodes ?? [])),
    ].sort();
    const operational = [
      ...new Set(
        cases
          .map((c) => c.backend?.operationalStatus)
          .filter((value): value is string => !!value),
      ),
    ].sort();
    const located: Record<string, [number, number]> = {};
    for (const item of this.explore.values())
      if (item.destination_city && item.destination)
        located[item.destination_city] = [item.destination.lat, item.destination.lng];
    const cities = [
      ...new Set([
        ...this.cities,
        ...cases.flatMap((c) => [c.shipment.origin, c.shipment.destination]),
      ]),
    ]
      .filter((city) => city && city !== "—")
      .sort();
    return {
      source: "backend",
      causes: causes.map((value) => ({ value, label: humanize(value) })),
      operational: operational.map((value) => ({
        value,
        label: humanize(value),
        arabic: OPERATIONAL[value] ?? humanize(value),
      })),
      cities,
      cityLocations: { ...located, ...moreCityLocations, ...cityLocations },
      facilities: [...this.facilities.values()],
    };
  }

  // The lab's local simulation has no counterpart here: nothing in the browser advances a case.
  tick() {}
  addCase(): string {
    throw new Error("Cases are opened by the backend monitor, not by this page.");
  }
  reset() {
    throw new Error("The operations ledger cannot be reset from this page.");
  }
  answer() {
    return "";
  }
}
