import type { OperationalCase } from "@/domain/types";
import { dateTimeLabel } from "@/lib/dates";
import { usePreferences } from "@/state/preferences";

/**
 * Chronological evidence list sorted by occurrence time. Receipt times are shown separately.
 * Route observation ranges use observation extrema, not backend summary first/last when they differ.
 */
export function EvidenceChronology({
  c,
  selected,
  onSelect,
}: {
  c: OperationalCase;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { t } = usePreferences();
  const route = c.backend?.routeEvidence;
  const items = [...c.evidence]
    .filter((e) => e.selectable !== false)
    .sort((a, b) =>
      (a.occurredAt ?? "9999").localeCompare(b.occurredAt ?? "9999"),
    );
  if (!items.length && !route) return null;
  return (
    <section className="detail-section" data-testid="evidence-chronology">
      <h3>{t("Evidence chronology", "التسلسل الزمني للأدلة")}</h3>
      {route && (
        <p className="finding-meta" data-testid="route-evidence-range">
          {t(
            `Vehicle observations at cutoff ${dateTimeLabel(route.asOf)}`,
            `ملاحظات المركبة عند ${dateTimeLabel(route.asOf)}`,
          )}
          {route.firstObservedAt && route.lastObservedAt && (
            <>
              {" · "}
              {t(
                `${dateTimeLabel(route.firstObservedAt)} → ${dateTimeLabel(route.lastObservedAt)}`,
                `${dateTimeLabel(route.firstObservedAt)} → ${dateTimeLabel(route.lastObservedAt)}`,
              )}
            </>
          )}
          {route.sampled &&
            ` · ${t("sampled for display", "عينة للعرض")}`}
          {route.summaryMismatch &&
            ` · ${t(
              "summary timestamps on the server may disagree with these observations",
              "قد لا تطابق الطوابع في الملخص هذه الملاحظات",
            )}`}
        </p>
      )}
      {c.backend?.investigationAsOf && (
        <p className="finding-meta" data-testid="investigation-cutoff">
          {t(
            `Investigation evidence snapshot ${dateTimeLabel(c.backend.investigationAsOf)}`,
            `لقطة أدلة التحقيق ${dateTimeLabel(c.backend.investigationAsOf)}`,
          )}
          {c.backend.asOf &&
            c.backend.investigationAsOf !== c.backend.asOf &&
            ` · ${t(
              `case detail as of ${dateTimeLabel(c.backend.asOf)}`,
              `تفاصيل الحالة عند ${dateTimeLabel(c.backend.asOf)}`,
            )}`}
        </p>
      )}
      <ol className="evidence-chronology">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={`chronology-item ${selected === item.id ? "selected" : ""}`}
              onClick={() => onSelect(item.id)}
              data-testid={`chronology-${item.id}`}
            >
              <span className="chronology-time">
                {item.occurredAt
                  ? dateTimeLabel(item.occurredAt)
                  : item.time}
              </span>
              <span className="chronology-label">{item.label}</span>
              {item.recordedAt && item.recordedAt !== item.occurredAt && (
                <span className="chronology-receipt">
                  {t(
                    `Received ${dateTimeLabel(item.recordedAt)}`,
                    `استُلم ${dateTimeLabel(item.recordedAt)}`,
                  )}
                </span>
              )}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
