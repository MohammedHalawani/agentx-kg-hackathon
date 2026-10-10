/**
 * The original browser-only UI lab: fixture cases, a local timer-driven mock service and
 * scripted assistant replies. Imported only by lab builds (VITE_SUHAIL_DATA=lab); the
 * connected product never loads this module.
 */
import { MockOperationsService } from "@/services/mock-operations";
import { MockCanopusService } from "@/services/mock-canopus";
import { parsePageIntent } from "@/services/mock-intents";
import type { CanopusSnapshotReader } from "@/domain/canopus";

export function createLabOperations() {
  let storage: Storage | undefined;
  try {
    storage = window.localStorage;
  } catch {
    /* Browser storage is optional. */
  }
  return new MockOperationsService(storage);
}
export const createLabCanopus = (reader: CanopusSnapshotReader) =>
  new MockCanopusService(reader);
export { parsePageIntent };
export { LabSettings } from "@/lab/settings-lab";
