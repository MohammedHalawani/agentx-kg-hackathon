import { describe, expect, it } from "vitest";
import { applyDetail, caseFromQueue } from "@/api/adapters";
import type { ApiBrief, ApiQueueCase } from "@/api/contracts";
import type { OperationalCase } from "@/domain/types";
import {
  byRecordedPriority,
  lastUpdateOf,
  nextActionOf,
} from "@/domain/priority";
import {
  answerOps,
  inView,
  parseOpsRequest,
  viewRows,
} from "@/domain/operations-assistant";
import {
  isReviewedDisposition,
  lastConfirmedCustody,
  proofOfDelivery,
} from "@/domain/work-order";
import {
  applyOpsView,
  canUndoOpsView,
  clearOpsView,
  resetOpsView,
  undoOpsView,
} from "@/state/ops-view";
import { ApiOperationsService } from "@/services/api-operations";
import { CASE_A, detailA, queueRows } from "../fixtures/backend";

const brief = (overrides: Partial<ApiBrief> = {}): ApiBrief => ({
  resolved: false,
  waiting_kind: "awaiting_operator_decision",
  waiting_label_en: "Waiting for a person",
  lines: [
    {
      key: "problem",
      label_en: "Problem",
      text_en: "A handover was not confirmed.",
    },
    {
      key: "finding",
      label_en: "Finding",
      text_en: "The investigation suggests a gap in the custody chain.",
    },
    {
      key: "status",
      label_en: "Current status",
      text_en: "Approve or reject the reconciliation.",
    },
  ],
  suspected_cause: {
    status: "hypothesis_not_accepted",
    label_en: "a gap in the custody chain",
    text_en: "...",
  },
  evidence: [
    {
      id: "SYN-SHP-000101-CUST-02-01",
      label_en: "Depot custody scan",
      in_graph: true,
    },
  ],
  ...overrides,
});

const row = (overrides: Partial<ApiQueueCase>): OperationalCase =>
  caseFromQueue({ ...queueRows[0], ...overrides });

describe("Decision view gating", () => {
  it("shows a work order only for a loaded, reviewed disposition", () => {
    const base = caseFromQueue(queueRows[0]);
    expect(isReviewedDisposition(applyDetail(base, detailA()))).toBe(false); // no brief
    const reviewed = applyDetail(base, detailA({ brief: brief() }));
    expect(isReviewedDisposition(reviewed)).toBe(true);
    for (const state of [
      "OPEN",
      "REOPENED",
      "INVESTIGATING",
      "RECOMMENDATION_READY",
    ] as const) {
      const running = applyDetail(
        base,
        detailA({
          workflow_state: state,
          brief: brief({ waiting_kind: "investigating" }),
        }),
      );
      expect(isReviewedDisposition(running)).toBe(false);
    }
    // A brief still saying "investigating" never yields a work order, whatever the state says.
    expect(
      isReviewedDisposition(
        applyDetail(
          base,
          detailA({ brief: brief({ waiting_kind: "investigating" }) }),
        ),
      ),
    ).toBe(false);
  });
  it("never treats GPS as custody, and shows proof only for delivery problems", () => {
    const c = applyDetail(
      caseFromQueue(queueRows[0]),
      detailA({ brief: brief() }),
    );
    const custody = lastConfirmedCustody(c);
    if (custody) {
      expect(custody.kind).not.toBe("gps");
      expect(custody.confidence).toBe("confirmed");
    }
    expect(proofOfDelivery(c).relevant).toBe(false);
    const dispute = applyDetail(
      caseFromQueue({
        ...queueRows[0],
        operational_status: "DELIVERY_DISPUTE",
      }),
      detailA({ operational_status: "DELIVERY_DISPUTE", brief: brief() }),
    );
    expect(proofOfDelivery(dispute).relevant).toBe(true);
    expect(
      proofOfDelivery(dispute).photos.every(
        (p) => !p.media || /^(\/|https?:)/.test(p.media),
      ),
    ).toBe(true);
  });
});

describe("Operations priority stays the recorded value", () => {
  it("orders High, Medium, Low, Unknown and keeps FIFO within a priority", () => {
    const cases = [
      row({
        case_id: "a",
        priority: "medium",
        opened_at: "2026-09-03T08:00:00+00:00",
      }),
      row({
        case_id: "b",
        priority: "high",
        opened_at: "2026-09-03T10:00:00+00:00",
      }),
      row({
        case_id: "c",
        priority: "unknown",
        opened_at: "2026-09-03T07:00:00+00:00",
      }),
      row({
        case_id: "d",
        priority: "high",
        opened_at: "2026-09-03T09:00:00+00:00",
      }),
      row({
        case_id: "e",
        priority: "low",
        opened_at: "2026-09-03T06:00:00+00:00",
      }),
    ];
    const before = cases.map((c) => c.priority);
    expect([...cases].sort(byRecordedPriority).map((c) => c.id)).toEqual([
      "d",
      "b",
      "a",
      "e",
      "c",
    ]);
    expect(cases.map((c) => c.priority)).toEqual(before); // nothing recalculated
  });
  it("never invents an action for an uninvestigated case", () => {
    const open = row({ workflow_state: "OPEN" });
    expect(nextActionOf(open)).toMatchObject({
      pending: true,
      label: ["Awaiting investigation", expect.any(String)],
    });
    const person = row({ workflow_state: "HUMAN_REVIEW" });
    expect(nextActionOf(person).label[0]).toBe("Person review needed");
    expect(lastUpdateOf(open)).toBe(open.openedAt);
  });
});

describe("Operations assistant (rule-based, visible, reversible)", () => {
  const cases = [
    row({
      case_id: "barcode",
      symptom_codes: ["BARCODE_READ_DIFFERS"],
      priority: "medium",
      workflow_state: "OPEN",
    }),
    row({
      case_id: "late",
      symptom_codes: ["MILESTONE_OVERDUE"],
      priority: "medium",
      workflow_state: "AWAITING_OUTCOME",
    }),
    row({
      case_id: "person",
      symptom_codes: [],
      priority: "high",
      workflow_state: "HUMAN_REVIEW",
    }),
    row({
      case_id: "closed",
      symptom_codes: ["BARCODE_READ_DIFFERS"],
      priority: "high",
      workflow_state: "RESOLVED",
    }),
  ];
  it.each([
    ["Show the five most urgent cases", { kind: "urgent", limit: 5 }],
    ["Show the 3 most urgent", { kind: "urgent", limit: 3 }],
    ["Which cases are overdue?", { kind: "overdue" }],
    ["Filter to barcode problems", { kind: "problem", problem: "barcode" }],
    [
      "Show the shipments waiting for custody verification",
      { kind: "custody_wait" },
    ],
    ["Which cases need immediate human attention?", { kind: "human" }],
    ["Show high priority cases", { kind: "priority", priority: "high" }],
    ["اعرض أكثر خمس حالات إلحاحاً", { kind: "urgent", limit: 5 }],
    ["صفِّ إلى مشكلات الباركود", { kind: "problem", problem: "barcode" }],
  ])("parses %s", (text, view) => {
    expect(parseOpsRequest(text)).toEqual({ type: "view", view });
  });
  it("answers from loaded cases only and never includes closed cases", () => {
    expect(
      viewRows({ kind: "problem", problem: "barcode" }, cases).map((c) => c.id),
    ).toEqual(["barcode"]);
    expect(viewRows({ kind: "overdue" }, cases).map((c) => c.id)).toEqual([
      "late",
    ]);
    expect(viewRows({ kind: "human" }, cases).map((c) => c.id)).toEqual([
      "person",
    ]);
    expect(
      viewRows({ kind: "urgent", limit: 2 }, cases).map((c) => c.id),
    ).toEqual(["person", "barcode"]);
    expect(inView({ kind: "urgent", limit: 5 }, cases[3])).toBe(false);
    const answer = answerOps("Which cases are overdue?", cases);
    expect(answer.caseIds).toEqual(["late"]);
    expect(answer.text[0]).toMatch(/1 in the loaded queue/);
    expect(answerOps("delete all cases", cases).view).toBeNull();
  });
  it("keeps every applied view reversible", () => {
    resetOpsView();
    applyOpsView({ kind: "overdue" }, "overdue");
    applyOpsView({ kind: "human" }, "human");
    expect(canUndoOpsView()).toBe(true);
    undoOpsView();
    clearOpsView();
    undoOpsView();
    resetOpsView();
    expect(canUndoOpsView()).toBe(false);
  });
});

describe("Canopus case answers stay with their case", () => {
  const service = (answer: Record<string, unknown>) => {
    const s = new ApiOperationsService({
      baseUrl: "http://stand-in",
      token: "t",
    } as never);
    (s as unknown as { client: { post: () => Promise<unknown> } }).client = {
      post: async () => answer,
    };
    return s;
  };
  const answer = {
    case_id: CASE_A,
    workflow_state: "HUMAN_REVIEW",
    kind: "record_answer",
    answer_en: "Recorded facts only.",
    model: null,
  };
  it("accepts an answer for the case asked about and labels a record answer", async () => {
    const result = await service(answer).askCanopus!(
      CASE_A,
      "What happened?",
      "en",
      [],
    );
    expect(result.kind).toBe("record_answer");
    expect(result.model ?? null).toBeNull();
  });
  it("discards an answer that belongs to another case", async () => {
    await expect(
      service({ ...answer, case_id: "SYN-CASE-OTHER" }).askCanopus!(
        CASE_A,
        "What happened?",
        "en",
        [],
      ),
    ).rejects.toThrow(/different case/);
  });
});
