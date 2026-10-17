import { useSyncExternalStore } from "react";
import type { OpsView } from "@/domain/operations-assistant";

/**
 * The view the Operations assistant applied to the table, shared by the Canopus panel and the
 * Operations page. Browser memory only: nothing is sent to the backend. Every change keeps
 * the previous view so Undo restores exactly what the operator saw before.
 */
export interface AppliedView {
  view: OpsView;
  request: string;
  appliedAt: string;
}
let current: AppliedView | null = null;
let previous: (AppliedView | null)[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function applyOpsView(view: OpsView, request: string) {
  previous = [...previous, current].slice(-10);
  current = { view, request, appliedAt: new Date().toISOString() };
  emit();
}
export function clearOpsView() {
  if (!current) return;
  previous = [...previous, current].slice(-10);
  current = null;
  emit();
}
/** Restores the view before the last change. */
export function undoOpsView() {
  if (!previous.length) return;
  current = previous.at(-1) ?? null;
  previous = previous.slice(0, -1);
  emit();
}
export function canUndoOpsView() {
  return previous.length > 0;
}
/** Test helper. */
export function resetOpsView() {
  current = null;
  previous = [];
  emit();
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
export function useOpsView() {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
}
export function useCanUndoOpsView() {
  return useSyncExternalStore(
    subscribe,
    () => previous.length > 0,
    () => false,
  );
}
