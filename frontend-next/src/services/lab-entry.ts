/**
 * The connected product's view of the UI lab: absent. Lab builds (vite --mode lab) alias this
 * module to ./lab.ts, which supplies the fixture service, the scripted assistant and the lab
 * settings. Because the swap happens at build time, the connected bundle contains no lab code.
 */
import type { ComponentType } from "react";
import type { CanopusService, CanopusSnapshotReader } from "@/domain/canopus";
import type { AssistantContext, IntentResult } from "@/domain/page-actions";
import type { OperationalCase, OperationsService } from "@/domain/types";

export type IntentParser = (
  message: string,
  context: AssistantContext,
  cases: OperationalCase[],
  language: "en" | "ar",
) => IntentResult;

export const createLabOperations = null as (() => OperationsService) | null;
export const createLabCanopus = null as
  | ((reader: CanopusSnapshotReader) => CanopusService)
  | null;
export const parsePageIntent = null as IntentParser | null;
export const LabSettings = null as ComponentType | null;
