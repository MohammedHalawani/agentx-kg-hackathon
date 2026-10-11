import { Network, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { OperationalCase } from "@/domain/types";
import { secondsLabel } from "@/lib/dates";
import { usePreferences } from "@/state/preferences";

const readable = (code: string) => code.replaceAll("_", " ").toLowerCase();

/**
 * What the investigation did, read from the backend's run record: each evidence query the
 * investigator chose, the model-call budget, the independent reviewer's output per round, and
 * the authority policy's decision. Nothing here is composed by the browser. Backend cases only.
 */
export function InvestigationRecord({ c }: { c: OperationalCase }) {
  const { t } = usePreferences();
  const log = c.backend?.investigationLog;
  const authority = c.backend?.authority;
  if (!c.backend || (!log && !authority)) return null;
  const beyond = log?.steps.reduce((sum, step) => sum + step.beyondShipment, 0) ?? 0;
  const timing = c.backend.timing;
  return (
    <>
      {log && (
        <section className="detail-section" data-testid="investigation-steps">
          <h3>{t("How Suhail investigated", "كيف حقق سهيل")}</h3>
          <div>
            <p className="finding-meta">
              {t(
                `${log.steps.length} evidence queries chosen by the investigator`,
                `${log.steps.length} استعلام أدلة اختارها المحقق`,
              )}
              {log.modelCallsUsed !== null &&
                ` · ${t(
                  `${log.modelCallsUsed} of ${log.modelCallCap ?? "?"} model calls`,
                  `${log.modelCallsUsed} من ${log.modelCallCap ?? "?"} استدعاء للنموذج`,
                )}`}
              {log.citations &&
                ` · ${t(
                  `${log.citations.valid} of ${log.citations.cited} citations valid`,
                  `${log.citations.valid} من ${log.citations.cited} استشهاداً صحيحاً`,
                )}`}
              {beyond > 0 &&
                ` · ${t(
                  `${beyond} records from beyond this shipment`,
                  `${beyond} سجلاً من خارج هذه الشحنة`,
                )}`}
            </p>
            {timing?.totalSeconds != null && (
              <p className="finding-meta" data-testid="investigation-timing">
                {t(
                  `Investigated in ${secondsLabel(timing.totalSeconds)}`,
                  `استغرق التحقيق ${secondsLabel(timing.totalSeconds)}`,
                )}
                {timing.firstConclusionSeconds != null &&
                  ` · ${t(
                    `first conclusion at ${secondsLabel(timing.firstConclusionSeconds)}`,
                    `أول استنتاج عند ${secondsLabel(timing.firstConclusionSeconds)}`,
                  )}`}
                {timing.modelSeconds != null &&
                  ` · ${t(
                    `${secondsLabel(timing.modelSeconds)} in model calls`,
                    `${secondsLabel(timing.modelSeconds)} في استدعاءات النموذج`,
                  )}`}
                {` · ${t("measured by the backend", "قياس الخادم")}`}
              </p>
            )}
            {log.capReached && log.degraded.length === 0 && (
              <p className="finding-caution">
                {t(
                  "The model-call cap was reached. No diagnosis was substituted; the case went to a person.",
                  "بلغ التحقيق حد استدعاءات النموذج. لم يُستبدل تشخيص، وأُحيلت الحالة إلى شخص.",
                )}
              </p>
            )}
            {log.degraded.map((item) => (
              <p className="finding-caution" key={item}>
                {item}
              </p>
            ))}
            <ol className="investigation-steps">
              {log.steps.map((step, index) => (
                <li key={index} className={step.failure ? "failed" : ""}>
                  <span className="step-index">{index + 1}</span>
                  <div>
                    <b>{readable(step.tool)}</b>
                    {step.round > 0 && (
                      <Badge variant="secondary" className="finding-status">
                        {t("revision round", "جولة مراجعة")}
                      </Badge>
                    )}
                    {step.beyondShipment > 0 && (
                      <Badge
                        variant="secondary"
                        className="finding-status finding-cross"
                      >
                        <Network size={10} />
                        {t("cross-shipment", "عبر الشحنات")}
                      </Badge>
                    )}
                    {step.purpose && <p>{step.purpose}</p>}
                    <small dir="ltr">
                      {step.failure
                        ? t(
                            `query failed (${readable(step.failure)}); not treated as absence of evidence`,
                            `فشل الاستعلام (${readable(step.failure)})؛ لا يُعد غياباً للأدلة`,
                          )
                        : `${step.records} ${t("records", "سجلات")}${step.args ? ` · ${step.args}` : ""}`}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
            {log.nextEvidenceStep && (
              <div className="finding">
                <b>{t("Next evidence step", "خطوة الأدلة التالية")}</b>
                <p>{log.nextEvidenceStep}</p>
              </div>
            )}
          </div>
        </section>
      )}
      {log && log.reviews.length > 0 && (
        <section className="detail-section" data-testid="review-rounds">
          <h3>{t("Reviewer, round by round", "المراجع، جولة بجولة")}</h3>
          <div>
            {log.reviews.map((review) => (
              <div className="finding" key={review.round}>
                <Badge
                  variant="secondary"
                  className={`finding-status finding-${/ACCEPT/i.test(review.verdict) ? "supported" : "uncertain"}`}
                >
                  {readable(review.verdict)}
                </Badge>
                <b>
                  {review.byModel
                    ? t(
                        `Independent model review · round ${review.round + 1}`,
                        `مراجعة نموذج مستقلة · الجولة ${review.round + 1}`,
                      )
                    : t(
                        `Review unavailable or deterministic · round ${review.round + 1}`,
                        `مراجعة غير متاحة أو حتمية · الجولة ${review.round + 1}`,
                      )}
                </b>
                {review.feedback && <p>{review.feedback}</p>}
                {review.unsupportedClaims.length > 0 && (
                  <>
                    <p>{t("Unsupported claims:", "ادعاءات غير مدعومة:")}</p>
                    <ul>
                      {review.unsupportedClaims.map((claim) => (
                        <li key={claim}>{claim}</li>
                      ))}
                    </ul>
                  </>
                )}
                {review.unaddressedContradictions.length > 0 && (
                  <>
                    <p>
                      {t(
                        "Contradictions not addressed:",
                        "تناقضات لم تُعالج:",
                      )}
                    </p>
                    <ul>
                      {review.unaddressedContradictions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            ))}
            {log.failedChecks.length > 0 && (
              <p className="finding-meta">
                {t("Deterministic checks not passed", "فحوص حتمية لم تُجتز")}:{" "}
                {log.failedChecks.join(", ").toLowerCase()}.{" "}
                {t(
                  "A failed check removes automatic authority; it never changes the diagnosis.",
                  "الفحص غير المجتاز يزيل الصلاحية التلقائية ولا يغيّر التشخيص.",
                )}
              </p>
            )}
          </div>
        </section>
      )}
      {authority && (
        <section className="detail-section" data-testid="authority-decision">
          <h3>
            <ShieldCheck size={13} className="inline me-1" />
            {t("Authority policy", "سياسة الصلاحيات")}
          </h3>
          <div>
            <p className="finding-meta">
              <b>{readable(authority.riskClass)}</b> ·{" "}
              <span dir="ltr">{authority.ruleId}</span>
              {authority.closure &&
                ` · ${t("closure", "الإغلاق")}: ${readable(authority.closure)}`}
            </p>
            <p className="finding-meta">{authority.reason}</p>
            <p className="finding-meta">
              {t(
                "Decided by deterministic policy on the backend, not by the model and not by this page.",
                "تقرره سياسة حتمية في الخادم، لا النموذج ولا هذه الصفحة.",
              )}
            </p>
          </div>
        </section>
      )}
    </>
  );
}
