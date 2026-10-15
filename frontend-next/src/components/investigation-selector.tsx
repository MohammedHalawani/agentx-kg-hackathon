import { Link } from "react-router-dom";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";

/** Navigation only: the backend retains every active investigation claim. */
export function InvestigationSelector({ selected }: { selected: string }) {
  const { connection } = useOperations();
  const { t } = usePreferences();
  const worker = connection?.worker;
  if (!worker) return null;
  return (
    <nav
      className="investigation-selector surface"
      aria-label={t("Investigation workers", "عمال التحقيق")}
      data-testid="investigation-selector"
    >
      <span className="worker-capacity">
        {t("Workers", "العمال")}{" "}
        <b>
          {worker.activeCount}/{worker.concurrency}
        </b>
      </span>
      {worker.activeCases.map((claim) => (
        <Link
          key={claim.caseId}
          to={`/cases/${encodeURIComponent(claim.caseId)}`}
          className={
            claim.caseId === selected ? "worker-case selected" : "worker-case"
          }
          aria-current={claim.caseId === selected ? "page" : undefined}
          data-testid={`worker-case-${claim.caseId}`}
        >
          <span className="live-dot" />
          <span>
            <b>{claim.workerId ?? t("Assigned worker", "عامل مكلّف")}</b>{" "}
            <span dir="ltr">{claim.shipmentId}</span>
          </span>
          <small>{claim.activeStage ?? claim.runStatus}</small>
        </Link>
      ))}
      <span className="worker-availability" role="status">
        {connection.state !== "online"
          ? t("Worker status unavailable", "حالة العمال غير متاحة")
          : t(
              `${Math.max(0, worker.concurrency - worker.activeCount)} slots available`,
              `${Math.max(0, worker.concurrency - worker.activeCount)} أماكن متاحة`,
            )}
        {worker.state === "paused" &&
          ` · ${t("Auto paused", "التلقائي متوقف")}`}
      </span>
    </nav>
  );
}
