import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { OperationalCase } from "@/domain/types";
import { usePreferences } from "@/state/preferences";

const statusLabel = {
  supported: ["Supported", "مدعوم"],
  refuted: ["Refuted", "مدحوض"],
  uncertain: ["Uncertain", "غير مؤكد"],
} as const;
const readable = (code: string | null) =>
  code ? code.replaceAll("_", " ").toLowerCase() : "—";

/**
 * The investigator's own findings as the backend recorded them: each hypothesis with its
 * status and the evidence it cites, and what the investigator said is missing. When the
 * independent reviewer did not accept the investigation, the findings are shown labelled as
 * claims, never as what happened. Backend cases only.
 */
export function InvestigatorFindings({
  c,
  onEvidence,
}: {
  c: OperationalCase;
  onEvidence: (id: string) => void;
}) {
  const { t } = usePreferences();
  const found = c.backend?.investigation;
  if (!c.backend || !found) return null;
  const drawn = (id: string) =>
    c.evidence.some((e) => e.id === id) || c.nodes.some((n) => n.id === id);
  return (
    <section className="detail-section" data-testid="investigator-findings">
      <h3>
        {found.accepted
          ? t("Investigator's findings", "نتائج المحقق")
          : t(
              "Investigator's findings · not accepted by the reviewer",
              "نتائج المحقق · لم يقبلها المراجع",
            )}
      </h3>
      <div>
        {!found.accepted && (
          <p className="finding-caution">
            <AlertTriangle size={13} />
            {t(
              "The independent reviewer did not accept this investigation. These are the investigator's claims, not what happened.",
              "لم يقبل المراجع المستقل هذا التحقيق. هذه ادعاءات المحقق وليست ما حدث.",
            )}
          </p>
        )}
        <p className="finding-meta">
          {t("Primary cause", "السبب الرئيسي")}:{" "}
          <b>{readable(found.primaryCause)}</b>
          {found.confidence &&
            ` · ${t("confidence", "الثقة")}: ${found.confidence}`}
          {` · ${found.toolCalls} ${t("evidence queries", "استعلامات أدلة")}`}
        </p>
        {found.hypotheses.map((h, index) => (
          <div className="finding" key={`${h.cause}-${index}`}>
            <Badge
              variant="secondary"
              className={`finding-status finding-${h.status}`}
            >
              {t(statusLabel[h.status][0], statusLabel[h.status][1])}
            </Badge>
            <b>{readable(h.cause)}</b>
            {h.assessment && <p>{h.assessment}</p>}
            {(
              [
                [t("Supporting", "داعمة"), h.supporting],
                [t("Contradicting", "مناقضة"), h.contradicting],
              ] as const
            )
              .filter(([, ids]) => ids.length > 0)
              .map(([label, ids]) => (
                <div className="finding-evidence" key={label}>
                  <small>{label}</small>
                  {ids.map((id) => (
                    <Button
                      key={id}
                      variant="outline"
                      size="sm"
                      disabled={!drawn(id)}
                      title={
                        drawn(id)
                          ? undefined
                          : t(
                              "Cited by the investigator; not among the records drawn on this screen",
                              "استشهد بها المحقق؛ ليست ضمن السجلات المرسومة في هذه الشاشة",
                            )
                      }
                      onClick={() => onEvidence(id)}
                    >
                      {id.replace(/^SYN-/, "")}
                    </Button>
                  ))}
                </div>
              ))}
          </div>
        ))}
        {found.missingEvidence.length > 0 && (
          <div className="finding">
            <b>{t("Missing evidence", "أدلة ناقصة")}</b>
            <ul>
              {found.missingEvidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}
        {found.requiresPhysicalCheck && (
          <p className="finding-meta">
            {t(
              "The investigator asked for a physical check.",
              "طلب المحقق فحصاً ميدانياً.",
            )}
          </p>
        )}
        {found.snapshotSuperseded && (
          <p className="finding-meta">
            {t(
              "Evidence kept arriving during the investigation; the case went to a person.",
              "استمر وصول الأدلة أثناء التحقيق؛ أُحيلت الحالة إلى شخص.",
            )}
          </p>
        )}
        {c.backend.evidenceAfterInvestigation > 0 && (
          <p className="finding-meta">
            {t(
              `${c.backend.evidenceAfterInvestigation} evidence records arrived after the investigation's snapshot and were not seen by it.`,
              `وصل ${c.backend.evidenceAfterInvestigation} سجل أدلة بعد لقطة التحقيق ولم يطّلع عليها.`,
            )}
          </p>
        )}
      </div>
    </section>
  );
}
