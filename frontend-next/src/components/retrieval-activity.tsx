import type { OperationalCase } from "@/domain/types";
import {
  evidenceFocus,
  retrievalEvents,
} from "@/domain/investigation-workspace";
import { usePreferences } from "@/state/preferences";
import { dateTimeLabel } from "@/lib/dates";

export function RetrievalActivity({
  c,
  selected,
  onFocus,
  onEvidence,
  following,
  onFollow,
}: {
  c: OperationalCase;
  selected: string | null;
  onFocus: (ids: string[], key: string) => void;
  onEvidence: (id: string) => void;
  following: boolean;
  onFollow: () => void;
}) {
  const { t } = usePreferences();
  const events = retrievalEvents(c.backend?.pipelineEvents).slice(-12);
  return (
    <section
      className="retrieval-activity"
      data-testid="retrieval-activity"
      aria-label={t("Recorded evidence retrieval", "استرجاع الأدلة المسجل")}
    >
      <div className="section-heading compact">
        <h3>{t("Evidence accessed", "الأدلة المسترجعة")}</h3>
        <button aria-pressed={following} onClick={onFollow}>
          {t("Follow live retrieval", "تتبع الاسترجاع الحي")}
        </button>
      </div>
      {!events.length && (
        <p className="muted">
          {t(
            "No investigator tool retrieval is recorded for this run yet.",
            "لم يُسجل استرجاع أدوات للمحقق في هذه الجولة بعد.",
          )}
        </p>
      )}
      <ol>
        {events.map((event) => {
          const key = `retrieval-${event.sequence}`;
          const output = event.output!;
          const ids = output.evidence_ids ?? [];
          const focus = evidenceFocus(c, ids);
          const cited = ids.filter((id) =>
            c.nodes.some((node) => node.id === id && node.cited),
          );
          return (
            <li
              key={event.sequence}
              className={selected === key ? "selected" : ""}
            >
              <button
                className="retrieval-operation"
                onClick={() => onFocus(ids, key)}
                aria-pressed={selected === key}
                data-testid={key}
              >
                <span>
                  <b>{output.tool}</b>
                  <small>
                    {t("Retrieved", "مسترجع")} · {ids.length}{" "}
                    {t("source IDs", "معرّفات مصدر")}
                    {cited.length > 0 &&
                      ` · ${cited.length} ${t("cited in findings/actions", "مستشهد بها في النتائج أو الإجراءات")}`}
                  </small>
                </span>
                <time>
                  {event.recorded_at
                    ? dateTimeLabel(event.recorded_at)
                    : `#${event.sequence}`}
                </time>
              </button>
              {output.purpose && (
                <p className="retrieval-purpose">
                  {t("Agent's stated question", "سؤال الوكيل المسجل")}:{" "}
                  {output.purpose}
                </p>
              )}
              {selected === key && (
                <div className="retrieval-sources">
                  {ids.slice(0, 20).map((id) => (
                    <button
                      key={id}
                      onClick={() => onEvidence(id)}
                      disabled={focus.missingIds.includes(id)}
                      dir="ltr"
                    >
                      {id}
                    </button>
                  ))}
                  {ids.length > 20 && (
                    <small>
                      {t(
                        `${ids.length - 20} more IDs in this recorded operation`,
                        `${ids.length - 20} معرّفات أخرى في العملية`,
                      )}
                    </small>
                  )}
                  {!focus.mapIds.length && (
                    <p>
                      {t(
                        "No grounded geographic link for these records; the map is unchanged.",
                        "لا رابط جغرافياً موثقاً لهذه السجلات؛ الخريطة لم تتغير.",
                      )}
                    </p>
                  )}
                  {focus.missingIds.length > 0 && (
                    <p>
                      {t(
                        `${focus.missingIds.length} retrieved records are unavailable in this bounded graph.`,
                        `${focus.missingIds.length} سجلات مسترجعة غير متاحة في هذا الرسم المحدود.`,
                      )}
                    </p>
                  )}
                  {!!output.computed_ids?.length && (
                    <p>
                      {t(
                        "Computed result IDs (not source graph nodes)",
                        "معرّفات نتائج محسوبة (ليست عقد مصدر)",
                      )}
                      : {output.computed_ids.join(", ")}
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <small className="muted">
        {t(
          "Retrieved evidence is distinct from cited findings and independently verified outcomes.",
          "الأدلة المسترجعة منفصلة عن الاستنتاجات المستشهدة والنتائج المتحقق منها مستقلاً.",
        )}
      </small>
    </section>
  );
}
