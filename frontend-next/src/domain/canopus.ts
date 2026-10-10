import type { CaseQueue } from "@/domain/types";
import type { ChatParticipant } from "@/domain/chat";

export type CanopusScreen =
  | "operations"
  | "investigation"
  | "decisions"
  | "explore"
  | "audit"
  | "settings";
export interface CanopusContext {
  screen: CanopusScreen;
  caseId?: string;
  selectedEvidenceId?: string | null;
  stage?: number;
  filters?: Record<string, string>;
}
export type CanopusReference = {
  id: string;
  label: string;
  kind:
    | "shipment"
    | "evidence"
    | "stage"
    | "decision"
    | "outcome"
    | "timeline"
    | "view";
  href: string;
};
export interface CanopusBlock {
  kind:
    "observation" | "hypothesis" | "recommendation" | "decision" | "outcome";
  text: string;
  references: CanopusReference[];
  verified?: boolean;
}
export interface CanopusReply {
  id: string;
  summary: string;
  blocks: CanopusBlock[];
  source: "synthetic";
  context: CanopusContext;
}
export interface CanopusRequest {
  id: string;
  message: string;
  context: CanopusContext;
  participant: ChatParticipant;
  language: "en" | "ar";
  /** UI-only fault injection for exercising the error and retry state. */
  simulateFailure?: boolean;
}
export type CanopusStreamEvent =
  | { type: "activity"; text: string }
  | { type: "delta"; text: string }
  | { type: "complete"; reply: CanopusReply };

/** Replace this adapter for a future integration; UI consumers only use this contract. */
export interface CanopusService {
  stream(
    request: CanopusRequest,
    options: { signal: AbortSignal },
  ): AsyncIterable<CanopusStreamEvent>;
}
export type CanopusSnapshotReader = () => CaseQueue;
