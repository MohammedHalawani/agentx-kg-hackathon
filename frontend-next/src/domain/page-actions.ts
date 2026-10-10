import type { CaseStatus, Scenario } from "@/domain/types";
export type TimeRange = "today" | "week" | "month" | "all" | "custom";
export interface ShipmentFilters {
  search: string;
  origin: string;
  destination: string;
  city: string;
  status: string;
  cause: string;
  priority: string;
}
export interface AuditFilters extends ShipmentFilters {
  shipmentId: string;
  kind: string;
  workflow: string;
  actor: string;
  timeRange: TimeRange;
  timeBasis: "recorded" | "evidence";
  sort: "oldest" | "newest";
  from: string;
  to: string;
}
export const emptyShipmentFilters: ShipmentFilters = {
  search: "",
  origin: "all",
  destination: "all",
  city: "all",
  status: "all",
  cause: "all",
  priority: "all",
};
export const emptyAuditFilters: AuditFilters = {
  ...emptyShipmentFilters,
  shipmentId: "all",
  kind: "all",
  workflow: "all",
  actor: "all",
  timeRange: "today",
  timeBasis: "recorded",
  sort: "oldest",
  from: "",
  to: "",
};
export type PageAction =
  | { type: "filter_shipments"; filters: Partial<ShipmentFilters> }
  | { type: "filter_audit_events"; filters: Partial<AuditFilters> }
  | { type: "select_shipment"; caseId: string }
  | { type: "focus_map"; city: string }
  | { type: "highlight_graph_evidence"; evidenceId: string }
  | {
      type: "change_view";
      view: "map" | "graph" | "schema" | "events" | "by_shipment" | "shipments";
    };
export interface AssistantContext {
  page: "explore" | "audit";
  selectedCaseId?: string;
  filters: ShipmentFilters | AuditFilters;
  view: string;
}
export interface IntentResult {
  actions: PageAction[];
  explanation: string;
  supported: boolean;
}
export const supportedStatuses: CaseStatus[] = [
  "queued",
  "investigating",
  "human_review",
  "needs_evidence",
  "executing",
  "verifying",
  "escalated",
  "resolved",
];
export const supportedScenarios: Scenario[] = [
  "barcode",
  "weight",
  "address",
  "custody",
  "contractor",
  "delivery",
  "failed",
  "normal",
];
