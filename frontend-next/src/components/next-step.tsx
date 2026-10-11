import { ArrowRight, CircleHelp, ListChecks, SearchX, ShieldAlert } from "lucide-react";
import type { OperationalCase } from "@/domain/types";
import { usePreferences } from "@/state/preferences";

const readable = (code: string | null | undefined) =>
  (code ?? "").replaceAll("_", " ").toLowerCase();

/**
 * Why an unresolved case is where it is and what it needs next, in plain words. Every
 * statement is the backend's own record (its next_step field): the rule that held the case,
 * the reviewer's verdict, the evidence it lists as missing, the actions already attempted and
 * their verified results. Nothing is inferred here, and a resolved case shows nothing.
 */
export function NextStep({ c }: { c: OperationalCase }) {
  const { t, preferences } = usePreferences();
  const step = c.backend?.nextStep;
  if (!step || step.resolved || c.status === "resolved") return null;
  const blocked = step.blockedBy;
  const waiting = step.actor !== "operator";
  return (
    <section
      className="surface next-step"
      aria-label={t("What this case needs", "ما تحتاجه هذه الحالة")}
      data-testid="next-step"
    >
      <div className="next-step-action">
        <ArrowRight size={15} />
        <div>
          <small>
            {waiting
              ? t("WHAT HAPPENS NEXT", "ما الذي يحدث بعد ذلك")
              : t("WHAT YOU NEED TO DO", "ما المطلوب منك")}
          </small>
          <p>{preferences.language === "ar" ? step.textAr || step.text : step.text}</p>
        </div>
      </div>
      <div className="next-step-facts">
        {blocked && (
          <div>
            <small>
              <ShieldAlert size={11} />
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
          <small>
            <SearchX size={11} />
            {t("EVIDENCE STILL MISSING", "أدلة ما زالت ناقصة")}
          </small>
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
          <small>
            <ListChecks size={11} />
            {t("ALREADY ATTEMPTED", "ما جُرّب بالفعل")}
          </small>
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
      </div>
      <p className="next-step-note">
        <CircleHelp size={11} />
        {t(
          "From the backend's records. The case is not resolved; only independent verification resolves a case.",
          "من سجلات الخادم. الحالة غير محلولة؛ لا تُحل الحالة إلا بتحقق مستقل.",
        )}
      </p>
    </section>
  );
}
