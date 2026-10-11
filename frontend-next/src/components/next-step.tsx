import { useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";
import type { OperationalCase } from "@/domain/types";
import { usePreferences } from "@/state/preferences";

const readable = (code: string | null | undefined) =>
  (code ?? "").replaceAll("_", " ").toLowerCase();

/**
 * The pipeline's final output: the next best action for the case, exactly as the backend
 * states it (its next_step record), with the recommended action beside it when one exists.
 * The reasons are one click away: the rule that held the case, the reviewer's objection, the
 * evidence listed as missing and what was already attempted, all from recorded fields.
 * Nothing is inferred here, and a case is never called resolved unless the backend says so.
 */
export function NextStep({ c }: { c: OperationalCase }) {
  const { t, preferences } = usePreferences();
  const [open, setOpen] = useState(false);
  const step = c.backend?.nextStep;
  if (!step) return null;
  const blocked = step.blockedBy;
  const details =
    !step.resolved &&
    (!!blocked || step.missingEvidence.length > 0 || step.attempted.length > 0);
  return (
    <div className="next-step" data-testid="next-step">
      <div className="next-step-action">
        <ArrowRight size={15} />
        <div>
          <small>{t("NEXT BEST ACTION", "أفضل إجراء تالٍ")}</small>
          <p>{preferences.language === "ar" ? step.textAr || step.text : step.text}</p>
          {!step.resolved && c.recommendation.available && (
            <span className="next-step-recommended">
              {t("Recommended action on record", "الإجراء الموصى به المسجل")}:{" "}
              {c.recommendation.title}
            </span>
          )}
        </div>
        {details && (
          <button
            type="button"
            className="next-step-toggle"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {t("Why, and what is missing", "السبب وما ينقص")}
            <ChevronDown size={13} className={open ? "open" : ""} />
          </button>
        )}
      </div>
      {details && open && (
        <div className="next-step-facts">
          {blocked && (
            <div>
              <small>
                {t(
                  "WHY SUHAIL DID NOT RESOLVE THIS AUTOMATICALLY",
                  "لماذا لم يحلها سهيل تلقائياً",
                )}
              </small>
              <p>
                {blocked.reason}{" "}
                <span className="next-step-rule" dir="ltr">
                  {blocked.ruleId}
                </span>
              </p>
              {blocked.reviewVerdict && (
                <p>
                  {t("Independent reviewer", "المراجع المستقل")}:{" "}
                  <b>{readable(blocked.reviewVerdict)}</b>
                  {blocked.reviewFeedback && ` · ${blocked.reviewFeedback}`}
                </p>
              )}
            </div>
          )}
          <div>
            <small>{t("EVIDENCE STILL MISSING", "أدلة ما زالت ناقصة")}</small>
            {step.missingEvidence.length ? (
              <ul>
                {step.missingEvidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>
                {t(
                  "The investigation listed no missing evidence.",
                  "لم يذكر التحقيق أدلة ناقصة.",
                )}
              </p>
            )}
          </div>
          <div>
            <small>{t("ALREADY ATTEMPTED", "ما جُرّب بالفعل")}</small>
            {step.attempted.length ? (
              <ul>
                {step.attempted.map((item, index) => (
                  <li key={index}>
                    <b>{readable(item.actionType)}</b> ·{" "}
                    {item.authority === "OPERATOR_APPROVAL"
                      ? t("approved by an operator", "بموافقة مشغل")
                      : t("automatic under policy", "تلقائي وفق السياسة")}{" "}
                    ·{" "}
                    {item.status === "ACKNOWLEDGED"
                      ? t("request delivered", "سُلّم الطلب")
                      : t("request not delivered", "لم يُسلّم الطلب")}
                    {item.verificationStatus
                      ? ` · ${
                          item.success
                            ? item.exceptionCleared === false
                              ? t("verified, the exception remains", "تم التحقق، الاستثناء باقٍ")
                              : t("verified as successful", "تم التحقق من نجاحه")
                            : t("verified as not successful", "تم التحقق من عدم نجاحه")
                        }${item.reason ? `: ${item.reason}` : ""}`
                      : item.status === "ACKNOWLEDGED"
                        ? ` · ${t("no verified outcome yet", "لا نتيجة متحقق منها بعد")}`
                        : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                {t(
                  "No corrective action has been carried out on this case.",
                  "لم يُنفذ أي إجراء تصحيحي في هذه الحالة.",
                )}
              </p>
            )}
          </div>
          <p className="next-step-note">
            {t(
              "From the backend's records. The full trail is in Case details and Audit. Only independent verification resolves a case.",
              "من سجلات الخادم. السجل الكامل في تفاصيل الحالة والتدقيق. لا تُحل الحالة إلا بتحقق مستقل.",
            )}
          </p>
        </div>
      )}
    </div>
  );
}
