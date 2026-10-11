import { useState } from "react";
import { CheckCircle2, ChevronDown, Hourglass, Send } from "lucide-react";
import type { OperationalCase } from "@/domain/types";
import { dateTimeLabel } from "@/lib/dates";
import { usePreferences } from "@/state/preferences";

/**
 * The case as one assessment: the problem, the finding, the review when it was challenged,
 * the action and the status, in the backend's own sentences (its `brief`, composed by code
 * from stored records). A pending action says who received the request, what is awaited and
 * until when. Confidence, the reviewer's original words, record ids and rule ids are in the
 * details, one click away. Nothing here is written by the browser.
 */
export function CaseAssessment({
  c,
  onEvidence,
}: {
  c: OperationalCase;
  onEvidence: (id: string) => void;
}) {
  const { t, preferences } = usePreferences();
  const [open, setOpen] = useState(false);
  const brief = c.backend?.brief;
  if (!brief) return null;
  const arabic = preferences.language === "ar";
  const say = (en?: string | null, ar?: string | null) =>
    arabic && ar ? ar : (en ?? "");
  const action = brief.actions?.[0];
  const pending =
    !!action && !action.outcome && action.status !== "not_delivered";
  // The backend's "action" line already carries the request, its recipient, what is awaited
  // and the deadline; the separate block is only for a brief without that line.
  const hasActionLine = (brief.lines ?? []).some(
    (line) => line.key === "action",
  );
  return (
    <div className="case-assessment" data-testid="case-assessment">
      <div className={`assessment-state ${brief.resolved ? "resolved" : ""}`}>
        {brief.resolved ? <CheckCircle2 size={13} /> : <Hourglass size={13} />}
        {say(brief.waiting_label_en, brief.waiting_label_ar) ||
          (brief.resolved
            ? t("Resolved and verified", "حُلّت وتم التحقق")
            : "")}
      </div>
      <dl>
        {(brief.lines ?? []).map((line) => (
          <div
            key={line.key}
            className={`assessment-line line-${line.key}`}
            data-testid={
              line.key === "action" && pending ? "pending-action" : undefined
            }
          >
            <dt>{say(line.label_en, line.label_ar)}</dt>
            <dd>{say(line.text_en, line.text_ar)}</dd>
          </div>
        ))}
      </dl>
      {pending && !hasActionLine && (
        <div className="assessment-pending" data-testid="pending-action">
          <Send size={12} />
          <div>
            <p>{say(action.text_en, action.text_ar)}</p>
            <p className="muted">
              {action.expected_response_at
                ? `${t("Typically answered by", "تُجاب عادةً قبل")} ${dateTimeLabel(action.expected_response_at)}`
                : t(
                    "When the answer will arrive is not known in advance.",
                    "موعد وصول الإجابة غير معروف مسبقاً.",
                  )}
            </p>
            {(action.deadline_text_en || action.deadline_at) && (
              <p className="muted">
                {say(action.deadline_text_en, action.deadline_text_ar) ||
                  `${t("Deadline", "الموعد النهائي")}: ${dateTimeLabel(action.deadline_at!)}`}
              </p>
            )}
          </div>
        </div>
      )}
      <button
        type="button"
        className="assessment-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {t("Evidence and technical details", "الأدلة والتفاصيل التقنية")}
        <ChevronDown size={12} className={open ? "open" : ""} />
      </button>
      {open && (
        <div className="assessment-details">
          {brief.suspected_cause && brief.suspected_cause.status !== "none" && (
            <section>
              <h4>{t("Suspected cause", "السبب المرجح")}</h4>
              <p>
                {say(
                  brief.suspected_cause.text_en,
                  brief.suspected_cause.text_ar,
                )}
              </p>
              {brief.suspected_cause.confidence && (
                <p className="muted">
                  {t(
                    "The model's own stated confidence",
                    "الثقة التي صرّح بها النموذج",
                  )}
                  : {brief.suspected_cause.confidence}
                </p>
              )}
            </section>
          )}
          {(brief.evidence ?? []).length > 0 && (
            <section>
              <h4>{t("Evidence it rests on", "الأدلة التي يستند إليها")}</h4>
              <ul>
                {brief.evidence!.map((item) => (
                  <li key={item.id}>
                    {item.in_graph ? (
                      <button
                        type="button"
                        onClick={() => onEvidence(item.id)}
                        title={item.id}
                      >
                        {say(item.label_en, item.label_ar) || item.id}
                      </button>
                    ) : (
                      <span title={item.id}>
                        {say(item.label_en, item.label_ar) || item.id}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {brief.review && (
            <section>
              <h4>{t("Independent review", "المراجعة المستقلة")}</h4>
              <p>{say(brief.review.text_en, brief.review.text_ar)}</p>
              {(brief.review.reason_summary_en ||
                brief.review.reason_original) && (
                <p className="muted">
                  {say(
                    brief.review.reason_summary_en,
                    brief.review.reason_summary_ar,
                  )}
                </p>
              )}
              {brief.review.reason_original && (
                <blockquote dir="ltr">
                  <small>
                    {t("The reviewer's own words", "كلام المراجع نفسه")}
                  </small>
                  {brief.review.reason_original}
                </blockquote>
              )}
            </section>
          )}
          {brief.policy && brief.policy.decision !== "none" && (
            <section>
              <h4>{t("Policy", "السياسة")}</h4>
              <p>{say(brief.policy.text_en, brief.policy.text_ar)}</p>
              {brief.policy.rule_id && (
                <p className="muted" dir="ltr">
                  {brief.policy.rule_id}
                  {brief.policy.rule_reason
                    ? ` · ${brief.policy.rule_reason}`
                    : ""}
                </p>
              )}
            </section>
          )}
          {brief.verification &&
            brief.verification.status !== "not_applicable" && (
              <section>
                <h4>{t("Verification", "التحقق")}</h4>
                <p>
                  {say(brief.verification.text_en, brief.verification.text_ar)}
                </p>
              </section>
            )}
          {brief.technical && (
            <p className="muted technical" dir="ltr">
              {[
                brief.technical.workflow_state,
                brief.technical.authority_rule_id,
                brief.technical.review_verdict,
                brief.technical.run_id,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
