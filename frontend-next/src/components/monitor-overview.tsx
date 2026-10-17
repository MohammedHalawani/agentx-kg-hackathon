import { useEffect, useMemo, useState } from "react";
import { ApiClient } from "@/api/client";
import { API_ORIGIN } from "@/config";
import { usePreferences } from "@/state/preferences";
import {
  monitorOverviewItems,
  type ApiMonitorOverview,
} from "@/lib/monitor-overview";

/** The monitor overview, polled from the backend; null until it answers. */
// eslint-disable-next-line react-refresh/only-export-components
export function useMonitorOverview(enabled = true, intervalMs = 10000) {
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
  return overview;
}

/**
 * Monitoring coverage, apart from case workflow: how many booked shipments the monitor has
 * checked and how many have no active exception. Before the monitor's first check of this
 * session it says so, rather than implying there is nothing to examine.
 */
export function MonitoringStatus({
  overview,
}: {
  overview: ApiMonitorOverview | null;
}) {
  const { t } = usePreferences();
  if (!overview) return null;
  const checked = overview.shipments_monitored;
  return (
    <p className="monitoring-status" data-testid="monitoring-status">
      <span className={checked ? "live-dot" : "paused-dot"} />
      {checked
        ? t(
            `Monitoring: ${checked} of ${overview.shipments_booked} booked shipments checked · ${overview.no_active_exception} with no active exception`,
            `المراقبة: فُحصت ${checked} من ${overview.shipments_booked} شحنة محجوزة · ${overview.no_active_exception} دون استثناء قائم`,
          )
        : t(
            `Monitoring is initializing: none of the ${overview.shipments_booked} booked shipments has been checked in this session yet.`,
            `المراقبة قيد التهيئة: لم تُفحص بعد أي من الشحنات المحجوزة (${overview.shipments_booked}) في هذه الجلسة.`,
          )}
    </p>
  );
}

/** One line of monitor counts for the Operations header, polled from the backend. Renders nothing until it has data. */
export function MonitorOverview({
  enabled = true,
  intervalMs = 10000,
}: {
  enabled?: boolean;
  intervalMs?: number;
}) {
  const { t } = usePreferences();
  const overview = useMonitorOverview(enabled, intervalMs);
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
