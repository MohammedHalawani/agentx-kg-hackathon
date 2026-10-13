import {
  facilities,
  initialSnapshot,
  makeCase,
  scenarioInfo,
} from "@/data/fixtures";
import { cityLocations } from "@/services/page-queries";
import {
  stages,
  type AuditKind,
  type AuthorityDecision,
  type CaseQueue,
  type OperationalCase,
  type OperationsCatalog,
  type OperationsService,
  type Scenario,
} from "@/domain/types";

export const STORAGE_KEY = "suhail-ui-lab.operations.v1";
export class MockOperationsService implements OperationsService {
  private snapshot: CaseQueue;
  private listeners = new Set<() => void>();
  private sequence = 0;
  constructor(
    private storage?: Pick<Storage, "getItem" | "setItem">,
    private now: () => string = () => new Date().toISOString(),
  ) {
    this.snapshot = initialSnapshot();
    try {
      const saved = storage?.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as CaseQueue;
        if (
          parsed.version === 1 &&
          Array.isArray(parsed.cases) &&
          Array.isArray(parsed.events) &&
          Array.isArray(parsed.decisions)
        ) {
          const seed = initialSnapshot();
          this.snapshot = {
            ...parsed,
            cases: [
              ...parsed.cases,
              ...seed.cases.filter(
                (c) => !parsed.cases.some((old) => old.id === c.id),
              ),
            ],
            events: [
              ...parsed.events,
              ...seed.events.filter(
                (e) => !parsed.events.some((old) => old.id === e.id),
              ),
            ],
          };
        }
      }
    } catch {
      /* A fresh fixture is safe when browser storage is unavailable. */
    }
  }
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private commit(snapshot: CaseQueue) {
    this.snapshot = { ...snapshot, revision: this.snapshot.revision + 1 };
    try {
      this.storage?.setItem(STORAGE_KEY, JSON.stringify(this.snapshot));
    } catch {
      /* Continue in memory if browser quota is exhausted. */
    }
    this.listeners.forEach((fn) => fn());
  }
  private event(
    c: OperationalCase,
    kind: AuditKind,
    title: string,
    detail: string,
    stage?: number,
  ) {
    return {
      id: `evt-${this.now()}-${++this.sequence}`,
      caseId: c.id,
      timestamp: this.now(),
      evidenceTimestamp: c.openedAt,
      runId: c.run?.id,
      evidenceIds:
        stage === 2
          ? ["origin", "handover"]
          : stage === 7
            ? c.outcome?.evidenceIds
            : ["origin"],
      actorRole:
        kind === "decision"
          ? ("operator" as const)
          : kind === "policy"
            ? ("reviewer" as const)
            : kind === "verification" || kind === "resolution"
              ? ("verifier" as const)
              : ("investigator" as const),
      kind,
      title,
      detail,
      stage,
      actor:
        kind === "decision" ? "Noura Al-Salem · operator" : `Suhail · ${kind}`,
      simulated: true as const,
    };
  }
  private update(
    c: OperationalCase,
    event: ReturnType<MockOperationsService["event"]>,
    decisions = this.snapshot.decisions,
  ) {
    this.commit({
      ...this.snapshot,
      cases: this.snapshot.cases.map((item) => (item.id === c.id ? c : item)),
      events: [event, ...this.snapshot.events],
      decisions,
    });
  }
  private find(id: string) {
    const c = this.snapshot.cases.find((c) => c.id === id);
    if (!c) throw new Error("Case not found.");
    return c;
  }
  setAutomatic(enabled: boolean) {
    this.commit({ ...this.snapshot, automatic: enabled });
  }
  investigate(id: string) {
    const c = this.find(id);
    if (c.status !== "queued")
      throw new Error(
        "This case already has an investigation. Opening a case does not create a new run.",
      );
    if (
      this.snapshot.cases.some((item) =>
        ["investigating", "executing", "verifying"].includes(item.status),
      )
    )
      throw new Error(
        "The current investigation must finish before another run can start.",
      );
    const updated = {
      ...c,
      status: "investigating" as const,
      run: { id: `RUN-${id}-${this.now()}`, stage: 0, startedAt: this.now() },
    };
    this.update(
      updated,
      this.event(
        updated,
        "investigation",
        "Investigation started",
        stages[0].detail,
        0,
      ),
    );
  }
  tick() {
    const current = this.snapshot.cases.find((c) =>
      ["investigating", "executing", "verifying"].includes(c.status),
    );
    if (!current) {
      if (this.snapshot.automatic) {
        const next = this.snapshot.cases
          .filter((c) => c.status === "queued")
          .sort((a, b) => Date.parse(a.openedAt) - Date.parse(b.openedAt))[0];
        if (next) this.investigate(next.id);
      }
      return;
    }
    if (current.status === "verifying") {
      this.verify(current.id);
      return;
    }
    if (current.status === "executing") {
      this.execute(current);
      return;
    }
    const stage = Math.min((current.run?.stage ?? 0) + 1, 7);
    let c: OperationalCase = { ...current, run: { ...current.run!, stage } };
    if (stage === 5) {
      const authority = c.recommendation.authority;
      if (authority === "operator")
        c = {
          ...c,
          status: "human_review",
          run: { ...c.run!, completedAt: this.now() },
        };
      if (authority === "evidence")
        c = {
          ...c,
          status: "needs_evidence",
          run: { ...c.run!, completedAt: this.now() },
        };
      if (authority === "automatic") c = { ...c, status: "executing" };
    }
    this.update(
      c,
      this.event(
        c,
        stages[stage].kind,
        stage === 5
          ? c.status === "human_review"
            ? "Operator authorization required"
            : c.status === "needs_evidence"
              ? "Independent evidence required"
              : "Low-risk action authorized"
          : stages[stage].label,
        stage === 4
          ? c.diagnosis
          : stage === 5
            ? c.recommendation.detail
            : stages[stage].detail,
        stage,
      ),
    );
  }
  decide(id: string, verdict: AuthorityDecision["verdict"], reason: string) {
    const c = this.find(id);
    if (c.status !== "human_review" && verdict !== "escalated")
      throw new Error("This case is not awaiting an operator decision.");
    if (c.status === "resolved")
      throw new Error("A verified case cannot be changed through an approval.");
    if (!reason.trim())
      throw new Error("Add a decision reason so it can be audited.");
    if (
      verdict === "approved" &&
      this.snapshot.cases.some(
        (item) =>
          item.id !== c.id &&
          ["investigating", "executing", "verifying"].includes(item.status),
      )
    )
      throw new Error(
        "Another run is active. Wait for it to finish before authorizing execution.",
      );
    const decision = {
      caseId: id,
      action: c.recommendation.title,
      verdict,
      actor: "Noura Al-Salem",
      timestamp: this.now(),
      reason: reason.trim(),
    };
    const updated: OperationalCase = {
      ...c,
      status:
        verdict === "approved"
          ? "executing"
          : verdict === "rejected"
            ? "needs_evidence"
            : "escalated",
      run: {
        id: c.run?.id ?? `RUN-${id}`,
        startedAt: c.run?.startedAt ?? this.now(),
        stage: verdict === "approved" ? 6 : (c.run?.stage ?? 5),
      },
    };
    this.update(
      updated,
      this.event(
        c,
        "decision",
        verdict === "approved"
          ? "Operator approved the action"
          : verdict === "rejected"
            ? "Action rejected · more evidence needed"
            : "Case escalated to dispatch supervision",
        `${c.recommendation.title}. Reason: ${reason.trim()}`,
      ),
      [decision, ...this.snapshot.decisions],
    );
  }
  private execute(c: OperationalCase) {
    const successful = c.scenario !== "failed";
    const updated: OperationalCase = {
      ...c,
      status: "verifying",
      run: { ...c.run!, stage: 7 },
      execution: {
        id: `EX-${c.id}-${this.now()}`,
        action: c.recommendation.title,
        timestamp: this.now(),
        successful,
        detail: successful
          ? "Authorized local action completed. Outcome requires a separate verification."
          : "Recovery instruction timed out. No new custody scan was received.",
      },
    };
    this.update(
      updated,
      this.event(
        c,
        "execution",
        successful
          ? "Action executed · awaiting verification"
          : "Action execution failed",
        updated.execution!.detail,
        6,
      ),
    );
  }
  verify(id: string) {
    const c = this.find(id);
    if (c.status !== "verifying" || !c.execution)
      throw new Error("There is no executed outcome ready for verification.");
    const successful =
      c.execution.successful &&
      c.scenario !== "failed" &&
      c.recommendation.authority !== "evidence";
    const outcome = {
      id: `OUT-${id}-${this.now()}`,
      timestamp: this.now(),
      successful,
      evidenceIds: successful ? ["origin", "recovery"] : [],
      detail: successful
        ? c.recommendation.expectedOutcome
        : "Independent custody evidence is absent. The case remains unresolved and is escalated.",
    };
    let updated: OperationalCase = {
      ...c,
      status: successful ? "resolved" : "escalated",
      outcome,
      run: { ...c.run!, stage: 7, completedAt: this.now() },
    };
    if (successful)
      updated = {
        ...updated,
        evidence: [
          ...c.evidence,
          {
            id: "recovery",
            label: "Recovery custody verified",
            kind: "custody",
            location:
              cityLocations[c.shipment.destination] ?? c.route.expected.at(-1)!,
            time: new Date(this.now()).toLocaleTimeString("en-GB", {
              timeZone: "Asia/Riyadh",
              hour: "2-digit",
              minute: "2-digit",
            }),
            detail: outcome.detail,
            confidence: "confirmed",
            facility: `${c.shipment.destination} gateway`,
          },
        ],
        nodes: [
          ...c.nodes,
          {
            id: "recovery",
            label: "Recovery scan",
            kind: "observation",
            detail: outcome.detail,
            evidenceId: "recovery",
          },
          {
            id: "outcome",
            label: "Verified outcome",
            kind: "outcome",
            detail: outcome.detail,
          },
        ],
        relationships: [
          ...c.relationships,
          {
            id: "recovery-scan",
            source: "package",
            target: "recovery",
            label: "CUSTODY_SCAN",
            detail: outcome.detail,
          },
          {
            id: "outcome-proof",
            source: "recovery",
            target: "outcome",
            label: "VERIFIES",
            detail: outcome.detail,
          },
        ],
      };
    this.update(
      updated,
      this.event(
        updated,
        "verification",
        successful
          ? "Outcome independently verified"
          : "Outcome verification failed",
        outcome.detail,
        7,
      ),
    );
    if (successful)
      this.commit({
        ...this.snapshot,
        events: [
          this.event(
            updated,
            "resolution",
            "Case moved to verified resolutions",
            "New parcel custody evidence independently confirms the action outcome.",
            7,
          ),
          ...this.snapshot.events,
        ],
      });
  }
  addCase(scenario: Scenario) {
    const numeric =
      Math.max(...this.snapshot.cases.map((c) => Number(c.id.slice(4)))) + 1;
    const id = `SHP-${numeric}`;
    const c = makeCase(id, scenario, this.now());
    this.commit({
      ...this.snapshot,
      cases: [c, ...this.snapshot.cases],
      events: [
        this.event(c, "intake", "New exception detected", c.summary),
        ...this.snapshot.events,
      ],
    });
    return id;
  }
  reset() {
    this.commit(initialSnapshot());
  }
  catalog(): OperationsCatalog {
    return {
      source: "lab",
      causes: Object.entries(scenarioInfo).map(([value, info]) => ({
        value,
        label: info.issue,
      })),
      operational: [
        { value: "held", label: "Parcel held", arabic: "الطرد محتجز" },
        {
          value: "disputed",
          label: "Delivery disputed",
          arabic: "تسليم محل نزاع",
        },
        { value: "exception", label: "Exception open", arabic: "استثناء مفتوح" },
      ],
      cities: Object.keys(cityLocations),
      cityLocations,
      facilities,
    };
  }
  answer(id: string, question: string) {
    const c = this.find(id),
      text = question.toLowerCase();
    if (/why.*review|approval|authority|مراجعة|صلاحية/.test(text))
      return `${c.diagnosis} This case ${c.status === "human_review" ? "requires operator approval" : `is ${c.status.replaceAll("_", " ")}`} because ${c.recommendation.authority === "operator" ? "the recommended action changes an operational assignment and needs explicit authority under policy C-04." : c.recommendation.authority === "evidence" ? "independent parcel evidence is missing." : "the low-risk action is eligible for automatic processing."} Proposed action: ${c.recommendation.title}.`;
    if (/where|custody|location|حيازة|أين/.test(text)) {
      const last = c.evidence
        .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
        .at(-1)!;
      return `Last confirmed parcel custody: ${last.facility} at ${last.time} (Saudi time), supported by “${last.label}”. ${last.detail} Vehicle GPS is separate telemetry and does not prove the parcel’s exact location.`;
    }
    if (/missing|scan|مفقود|مسح/.test(text)) {
      const missing = c.evidence.filter((e) => e.confidence === "missing");
      return `Unconfirmed observations: ${missing.map((e) => e.label).join("; ")}. ${c.scenario === "custody" ? "The outbound parcel handover is the missing custody link." : "Planned destination observations are not completed scans."} The case remains open until independent evidence establishes the outcome.`;
    }
    if (/recommend|action|إجراء|توصية/.test(text))
      return `Recommended action: ${c.recommendation.title}. ${c.recommendation.detail} Expected evidence: ${c.recommendation.expectedOutcome} Chat cannot authorize this action; use the explicit decision controls.`;
    return `${c.diagnosis} Evidence: ${c.evidence
      .filter((e) => e.confidence === "confirmed")
      .map((e) => `${e.label} (${e.time})`)
      .join(
        "; ",
      )}. This response is grounded in this synthetic fixture. Chat is read-only and cannot alter operational decisions.`;
  }
}
