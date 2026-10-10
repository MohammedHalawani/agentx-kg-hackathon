import type { PageAction } from "@/domain/page-actions";
import type { CanopusReply, CanopusRequest } from "@/domain/canopus";
export type ChatParticipant = "suhail" | "investigator" | "reviewer";
export interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  agent?: ChatParticipant;
  timestamp: string;
  actions?: PageAction[];
  reply?: CanopusReply;
  streaming?: boolean;
  error?: string;
  /** Retains the original context so each failed or interrupted reply can be retried. */
  request?: CanopusRequest;
}
