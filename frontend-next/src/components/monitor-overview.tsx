import { useEffect, useMemo, useState } from "react";
import { ApiClient } from "@/api/client";
import { API_ORIGIN } from "@/config";
import { usePreferences } from "@/state/preferences";
import {
  monitorOverviewItems,
  type ApiMonitorOverview,
} from "@/lib/monitor-overview";

/** One line of monitor counts for the Operations header, polled from the backend. Renders nothing until it has data. */
export function MonitorOverview({
  enabled = true,
  intervalMs = 10000,
}: {
  enabled?: boolean;
  intervalMs?: number;
}) {
  const { t } = usePreferences();
  const client = useMemo(() => new ApiClient({ origin: API_ORIGIN }), []);
  const [overview, setOverview] = useState<ApiMonitorOverview | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const read = () =>
      client
        .get<ApiMonitorOverview>("/operations/monitor/overview")
        .then((value) => live && setOverview(value))
        .catch(() => live && setOverview(null));
    void read();
    const timer = setInterval(read, intervalMs);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [client, enabled, intervalMs]);
  if (!overview) return null;
  return (
    <span
      className="inline-count monitor-overview"
      data-testid="monitor-overview"
    >
      {monitorOverviewItems(overview).map((item, index) => (
        <span key={item.key} title={t(item.title_en, item.title_ar)}>
          {index > 0 && <i>·</i>} {item.value} {t(item.en, item.ar)}
        </span>
      ))}
    </span>
  );
}
