import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { ApiClient } from "@/api/client";
import { ApiOperationsService } from "@/services/api-operations";
import { createLabOperations } from "@/services/lab-entry";
import { API_ORIGIN } from "@/config";
import type { OperationsService } from "@/domain/types";

const OperationsContext = createContext<OperationsService | null>(null);
/**
 * The connected product reads everything from the Suhail backend. The browser-only lab
 * service exists only in lab builds (see services/lab-entry.ts), and only the lab runs a
 * local timer.
 */
export function OperationsProvider({
  children,
  service: provided,
}: {
  children: ReactNode;
  service?: OperationsService;
}) {
  const [service] = useState<OperationsService>(
    () =>
      provided ??
      (createLabOperations
        ? createLabOperations()
        : new ApiOperationsService({
            client: new ApiClient({ origin: API_ORIGIN }),
          })),
  );
  useEffect(() => {
    if (service instanceof ApiOperationsService) {
      service.start();
      return () => service.stop();
    }
    // Lab only: the fixture service advances its own simulated cases.
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
  return useMemo(() => {
    const catalog = service.catalog();
    return {
      ...snapshot,
      service,
      catalog,
      /** True when cases come from the Suhail backend rather than lab fixtures. */
      backend: catalog.source === "backend",
    };
  }, [snapshot, service]);
}
