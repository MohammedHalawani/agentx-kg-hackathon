import { useState } from "react";
import { CheckCircle2, ChevronDown, Hourglass, Send } from "lucide-react";
import type { OperationalCase } from "@/domain/types";
import { dateTimeLabel } from "@/lib/dates";
import { usePreferences } from "@/state/preferences";
import {
  actionLabel,
  verifiedResolution,
  waitingLabel,
} from "@/domain/investigation-workspace";

/**
 * The case as one assessment: the problem, the finding, the review when it was challenged,
 * the action and the status, in the backend's own sentences (its `brief`, composed by code
 * from stored records). A pending action says who received the request, what is awaited and
 * until when. Confidence, the reviewer's original words, record ids and rule ids are in the
 * details, one click away. V3.2 operational labels come from its independent lifecycle
 * axes; the older brief's action/status wording cannot override those facts.
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
  const lifecycle = c.backend?.actionStatus;
  const resolved = lifecycle ? verifiedResolution(c) : brief.resolved;
  const statusLabel = resolved
    ? ["Verified resolved", "تم التحقق من الحل"]
    : waitingLabel(c);
  const currentAction = lifecycle?.actions[0];
  const arabic = preferences.language === "ar";
  const say = (en?: string | null, ar?: string | null) =>
    arabic && ar ? ar : (en ?? "");
  const action = brief.actions?.[0];
  const pending =
    !lifecycle &&
    !!action &&
    !action.outcome &&
    action.status !== "not_delivered";
  // The backend's "action" line already carries the request, its recipient, what is awaited
  // and the deadline; the separate block is only for a brief without that line.
  const hasActionLine = (brief.lines ?? []).some(
    (line) => line.key === "action",
  );
  return (
    <div className="case-assessment" data-testid="case-assessment">
      <div className={`assessment-state ${resolved ? "resolved" : ""}`}>
        {resolved ? <CheckCircle2 size={13} /> : <Hourglass size={13} />}
        {lifecycle
          ? t(statusLabel[0], statusLabel[1])
          : say(brief.waiting_label_en, brief.waiting_label_ar) ||
            (resolved ? t("Resolved and verified", "حُلّت وتم التحقق") : "")}
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
            <dd>
              {lifecycle && line.key === "status"
                ? t(statusLabel[0], statusLabel[1])
                : lifecycle && line.key === "action"
                  ? currentAction
                    ? t(...actionLabel(currentAction))
                    : t(
                        "No operational action is recorded.",
                        "لا إجراء تشغيلياً مسجلاً.",
                      )
                  : say(line.text_en, line.text_ar)}
            </dd>
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

/**
 * The full assessment as plain answers to the operator's questions, each one the backend's own
 * sentence from its brief. A hypothesis is marked as a hypothesis; "resolved" is stated only
 * when the backend's record says so.
 */
export function AssessmentAnswers({
  c,
  onEvidence,
}: {
  c: OperationalCase;
  onEvidence: (id: string) => void;
}) {
  const { t, preferences } = usePreferences();
  const brief = c.backend?.brief;
  if (!brief) return null;
  const arabic = preferences.language === "ar";
  const say = (en?: string | null, ar?: string | null) =>
    arabic && ar ? ar : (en ?? "");
  const cause = brief.suspected_cause;
  const action = brief.actions?.[0];
  const lifecycle = c.backend?.actionStatus;
  const resolved = lifecycle ? verifiedResolution(c) : brief.resolved;
  const next = c.backend?.nextStep;
  const rows: [string, string, React.ReactNode][] = [
    [
      "happened",
      t("What happened?", "ماذا حدث؟"),
      say(brief.what_happened?.text_en, brief.what_happened?.text_ar),
    ],
    [
      "cause",
      t("What does Suhail believe caused it?", "ما السبب في تقدير سهيل؟"),
      cause && cause.status !== "none" ? (
        <>
          <span
            className={`assessment-tag ${cause.status === "accepted" ? "accepted" : ""}`}
          >
            {cause.status === "accepted"
              ? t(
                  "Accepted by the review · not yet proven",
                  "قبلته المراجعة · لم يثبت بعد",
                )
              : t(
                  "Hypothesis · not accepted by the review",
                  "فرضية · لم تقبلها المراجعة",
                )}
          </span>
          {say(cause.text_en, cause.text_ar)}
        </>
      ) : (
        t(
          "The investigation reached no conclusion.",
          "لم يصل التحقيق إلى استنتاج.",
        )
      ),
    ],
    [
      "evidence",
      t("What evidence supports that?", "ما الأدلة التي تدعم ذلك؟"),
      (brief.evidence ?? []).length ? (
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
                say(item.label_en, item.label_ar) || item.id
              )}
            </li>
          ))}
        </ul>
      ) : (
        t("No cited evidence is recorded.", "لا توجد أدلة مستشهد بها مسجلة.")
      ),
    ],
    [
      "review",
      t("Did the independent review accept it?", "هل قبلته المراجعة المستقلة؟"),
      brief.review ? (
        <>
          {say(brief.review.text_en, brief.review.text_ar)}
          {brief.review.reason_summary_en && (
            <span className="assessment-reason">
              {say(
                brief.review.reason_summary_en,
                brief.review.reason_summary_ar,
              )}
            </span>
          )}
        </>
      ) : (
        ""
      ),
    ],
    [
      "action",
      t(
        "What action was taken or recommended?",
        "ما الإجراء المتخذ أو الموصى به؟",
      ),
      lifecycle
        ? lifecycle.actions[0]
          ? t(...actionLabel(lifecycle.actions[0]))
          : t("No operational action is recorded.", "لا إجراء تشغيلياً مسجلاً.")
        : say(action?.text_en, action?.text_ar) ||
          say(brief.policy?.text_en, brief.policy?.text_ar),
    ],
    [
      "next",
      t("What happens next?", "ما الذي يحدث بعد ذلك؟"),
      next ? (arabic ? next.textAr || next.text : next.text) : "",
    ],
    [
      "resolved",
      t("Is the shipment issue resolved?", "هل حُلّت مشكلة الشحنة؟"),
      <>
        <span className={`assessment-tag ${resolved ? "accepted" : ""}`}>
          {resolved
            ? t("Yes · independently verified", "نعم · تم التحقق المستقل")
            : t("No · not resolved", "لا · غير محلولة")}
        </span>
        {lifecycle
          ? resolved
            ? t(
                "Backend-verified case resolution.",
                "حل الحالة متحقق منه من الخادم.",
              )
            : t(...waitingLabel(c))
          : say(brief.verification?.text_en, brief.verification?.text_ar)}
      </>,
    ],
  ];
  return (
    <dl className="assessment-answers" data-testid="assessment-answers">
      {rows
        .filter(([, , answer]) => answer !== "")
        .map(([key, question, answer]) => (
          <div key={key}>
            <dt>{question}</dt>
            <dd>{answer}</dd>
          </div>
        ))}
    </dl>
  );
}
