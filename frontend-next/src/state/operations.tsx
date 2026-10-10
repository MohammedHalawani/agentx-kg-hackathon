import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { MockOperationsService } from "@/services/mock-operations";
import type { OperationsService } from "@/domain/types";
const OperationsContext = createContext<OperationsService | null>(null);
export function OperationsProvider({ children }: { children: ReactNode }) {
  const [service] = useState(() => {
    let storage: Storage | undefined;
    try {
      storage = window.localStorage;
    } catch {
      /* Browser storage is optional. */
    }
    return new MockOperationsService(storage);
  });
  useEffect(() => {
    const timer = window.setInterval(() => service.tick(), 2400);
    return () => window.clearInterval(timer);
  }, [service]);
  return (
    <OperationsContext.Provider value={service}>
      {children}
    </OperationsContext.Provider>
  );
}
export function useOperations() {
  const service = useContext(OperationsContext);
  if (!service) throw new Error("OperationsProvider missing");
  const snapshot = useSyncExternalStore(
    service.subscribe,
    service.getSnapshot,
    service.getSnapshot,
  );
  return useMemo(() => ({ ...snapshot, service }), [snapshot, service]);
}
