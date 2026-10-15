import { readFileSync } from "node:fs";
import type {
  ApiActionStatus,
  ApiOutcome,
  ApiCaseDetail,
} from "@/api/contracts";
import { applyDetail, caseFromQueue } from "@/api/adapters";
import { queueRows } from "./backend";

/** Actual exported store/verifier traces, not frontend-created successful outcomes. */
const wire = JSON.parse(
  readFileSync(
    new URL("./v32-action-status.wire.json", import.meta.url),
    "utf8",
  ),
);
export const actionTraces = wire.cases as Array<{
  workflow: string;
  case_id: string;
  shipment_id: string;
  workflow_state: ApiCaseDetail["workflow_state"];
  action_status: ApiActionStatus;
  outcome: ApiOutcome | null;
}>;
export function actionCase(index: number) {
  const trace = actionTraces[index];
  return applyDetail(
    caseFromQueue({
      ...queueRows[0],
      case_id: trace.case_id,
      shipment_id: trace.shipment_id,
    }),
    {
      case_id: trace.case_id,
      shipment_id: trace.shipment_id,
      workflow_state: trace.workflow_state,
      state_version: 1,
      evidence: { nodes: [], edges: [] },
      action_status: trace.action_status,
      outcome: trace.outcome,
    },
  );
}
