import { useState, type ReactNode } from "react";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  ChevronDown,
  Hourglass,
  ImageOff,
  Network,
  Send,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import type { OperationalCase } from "@/domain/types";
import { usePreferences } from "@/state/preferences";
import { dateTimeLabel } from "@/lib/dates";
import {
  actionLabel,
  verifiedResolution,
  waitingLabel,
} from "@/domain/investigation-workspace";
import { lastConfirmedCustody, proofOfDelivery } from "@/domain/work-order";

/**
 * The Decision view's one work order for a reviewed case, built only from what the backend
 * recorded: its brief (what happened, the finding and its review, the policy, the requests
 * sent and what each awaits, the verification), its next step and its action lifecycle.
 * Four facts lead (what happened, next best action, responsible party, current status); the
 * finding, action taken, evidence, completion requirements and technical record fold out.
 * Nothing is inferred: a hypothesis stays a hypothesis, the recipient of a request is not
 * called the custodian, a driver assignment is not custody, and "resolved" appears only when
 * the independent verifier recorded it.
 */
export function WorkOrder({
  c,
  onEvidence,
  onShowGraph,
  newEvidence,
  controls,
}: {
  c: OperationalCase;
  onEvidence: (id: string) => void;
  onShowGraph: () => void;
  /** Records that arrived since the operator opened this view. */
  newEvidence: number;
  controls: ReactNode;
}) {
  const { t, preferences } = usePreferences();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const brief = c.backend?.brief;
  if (!brief) return null;
  const arabic = preferences.language === "ar";
  const say = (en?: string | null, ar?: string | null) =>
    arabic && ar ? ar : (en ?? "");
  const lifecycle = c.backend?.actionStatus;
  const resolved = lifecycle ? verifiedResolution(c) : !!brief.resolved;
  const next = c.backend?.nextStep;
  const cause = brief.suspected_cause;
  const review = brief.review;
  const action = brief.actions?.[0];
  const currentAction = lifecycle?.actions[0];
  const custody = lastConfirmedCustody(c);
  const proof = proofOfDelivery(c);
  const line = (key: string) => (brief.lines ?? []).find((l) => l.key === key);
  const person =
    !resolved &&
    (lifecycle?.human_decision_required ||
      ["HUMAN_REVIEW", "ESCALATED", "AWAITING_APPROVAL"].includes(
        c.backend?.workflowState ?? "",
      ));
  // Why a person is needed, in the backend's own recorded words: the review's challenge, the
  // rule that held the case, or the authority policy.
  const reviewLine = line("review");
  const personReason =
    say(reviewLine?.text_en, reviewLine?.text_ar) ||
    next?.blockedBy?.reason ||
    say(brief.policy?.text_en, brief.policy?.text_ar);
  // With a V3.2 action lifecycle, its independent axes decide the status; the brief's older
  // status sentence cannot override them (as in the Evidence view's assessment).
  const statusLine = lifecycle
    ? ""
    : say(line("status")?.text_en, line("status")?.text_ar);
  const nextLine = next ? (arabic ? next.textAr || next.text : next.text) : "";
  const statusText = resolved
    ? t("Verified resolved", "تم التحقق من الحل")
    : lifecycle
      ? t(...waitingLabel(c))
      : say(brief.waiting_label_en, brief.waiting_label_ar);
  const toggle = (key: string) =>
    setOpen((value) => ({ ...value, [key]: !value[key] }));
  const Fold = ({
    id,
    title,
    summary,
    children,
  }: {
    id: string;
    title: string;
    summary?: ReactNode;
    children: ReactNode;
  }) => (
    <section className={`order-fold ${open[id] ? "open" : ""}`}>
      <button
        type="button"
        aria-expanded={!!open[id]}
        aria-controls={`order-${id}`}
        onClick={() => toggle(id)}
      >
        <span>{title}</span>
        {summary && !open[id] && <small>{summary}</small>}
        <ChevronDown size={13} />
      </button>
      {open[id] && (
        <div id={`order-${id}`} className="order-fold-body">
          {children}
        </div>
      )}
    </section>
  );
  const evidence = brief.evidence ?? [];
  const awaiting = action?.awaiting;
  const missing = next?.missingEvidence ?? [];
  return (
    <article
      className="work-order"
      data-testid="work-order"
      aria-label={t("Work order", "أمر العمل")}
    >
      <header className="order-header">
        <div>
          <small>{t("WORK ORDER", "أمر العمل")}</small>
          <h3 dir="ltr">{c.shipment.id}</h3>
        </div>
        <span
          className={`order-status ${resolved ? "resolved" : person ? "person" : "waiting"}`}
          data-testid="order-status"
        >
          {resolved ? (
            <CheckCircle2 size={13} />
          ) : person ? (
            <UserRound size={13} />
          ) : (
            <Hourglass size={13} />
          )}
          {statusText}
        </span>
        <button type="button" className="order-graph" onClick={onShowGraph}>
          <Network size={13} />
          {t("View knowledge graph", "عرض رسم المعرفة")}
        </button>
      </header>
      {newEvidence > 0 && (
        <p
          className="order-new-evidence"
          role="status"
          data-testid="order-new-evidence"
        >
          {t(
            `${newEvidence} new evidence record${newEvidence === 1 ? "" : "s"} arrived since you opened this view. The order below is updated; nothing is resolved until the verifier says so.`,
            `وصل ${newEvidence} من سجلات الأدلة الجديدة منذ فتح هذا العرض. حُدّث الأمر أدناه، ولا يُعد شيء محلولاً حتى يقرر المتحقق.`,
          )}
        </p>
      )}
      <dl className="order-primary">
        <div className="order-row" data-testid="order-happened">
          <dt>{t("What happened", "ماذا حدث")}</dt>
          <dd>
            {say(line("problem")?.text_en, line("problem")?.text_ar) ||
              say(brief.what_happened?.text_en, brief.what_happened?.text_ar)}
          </dd>
        </div>
        <div className="order-row emphasis" data-testid="order-next">
          <dt>{t("Next best action", "أفضل إجراء تالٍ")}</dt>
          <dd>
            <ArrowRight size={14} aria-hidden="true" />
            <span>
              {next
                ? arabic
                  ? next.textAr || next.text
                  : next.text
                : statusLine || statusText}
              {person && personReason && (
                <em className="order-why-person" data-testid="order-why-person">
                  {t("Why a person:", "لماذا يلزم شخص:")} {personReason}
                </em>
              )}
            </span>
          </dd>
        </div>
        <div className="order-row" data-testid="order-party">
          <dt>{t("Responsible party", "الطرف المسؤول")}</dt>
          <dd className="order-parties">
            {next?.actor === "operator" && !resolved && (
              <span>
                <UserRound size={12} />
                <b>{t("Suhail operator", "مشغل سهيل")}</b>
                <small>
                  {t(
                    "acts next, per the recorded next step",
                    "يتصرف تالياً حسب الخطوة المسجلة",
                  )}
                </small>
              </span>
            )}
            {action?.recipient?.known && action.recipient.label_en && (
              <span data-testid="order-recipient">
                <Send size={12} />
                <b dir="ltr">
                  {say(action.recipient.label_en, action.recipient.label_ar)}
                </b>
                <small>
                  {t(
                    "authorized recipient of the request (simulated)",
                    "المستلم المفوَّض للطلب (محاكاة)",
                  )}
                </small>
              </span>
            )}
            {custody && (
              <span data-testid="order-custodian">
                <Building2 size={12} />
                <b>{custody.facility}</b>
                <small>
                  {t("last confirmed custodian", "آخر حائز مؤكد")} ·{" "}
                  {custody.time} AST
                </small>
              </span>
            )}
            {!custody &&
              !(action?.recipient?.known && action.recipient.label_en) &&
              next?.actor !== "operator" && (
                <span className="muted">
                  {t(
                    "The records do not establish a responsible person or facility.",
                    "لا تثبت السجلات شخصاً أو منشأة مسؤولة.",
                  )}
                </span>
              )}
            <small className="order-note">
              {t(
                "From custody and request records only. A driver assignment is not custody, and Suhail contacts no one from here.",
                "من سجلات الحيازة والطلبات فقط. إسناد السائق ليس حيازة، ولا يتواصل سهيل مع أحد من هنا.",
              )}
            </small>
          </dd>
        </div>
        <div className="order-row" data-testid="order-status-row">
          <dt>{t("Current status", "الوضع الحالي")}</dt>
          <dd>
            {statusLine && statusLine !== nextLine ? statusLine : statusText}
            {!resolved &&
              !lifecycle &&
              brief.verification &&
              brief.verification.status !== "not_applicable" && (
                <span className="order-verification">
                  {say(brief.verification.text_en, brief.verification.text_ar)}
                </span>
              )}
          </dd>
        </div>
      </dl>
      <div className="order-controls">{controls}</div>
      {proof.relevant && (
        <section className="order-proof" data-testid="order-proof">
          <h4>{t("Proof of delivery", "إثبات التسليم")}</h4>
          {proof.photos.length ? (
            proof.photos.map((photo) => (
              <figure key={photo.id}>
                {photo.media ? (
                  <img src={photo.media} alt={photo.label} />
                ) : (
                  <span className="order-proof-missing">
                    <ImageOff size={14} />
                    {t(
                      "A photo record exists; no image file is attached to it.",
                      "يوجد سجل صورة، ولا يرفق به ملف صورة.",
                    )}
                  </span>
                )}
                <figcaption>
                  <button
                    type="button"
                    onClick={() => onEvidence(photo.id)}
                    dir="ltr"
                  >
                    {photo.id}
                  </button>{" "}
                  · {photo.detail}
                  {photo.media &&
                    ` · ${t("illustration attached for demonstration; not evidence of delivery", "صورة توضيحية للعرض وليست دليلاً على التسليم")}`}
                </figcaption>
              </figure>
            ))
          ) : (
            <p className="muted">
              {t(
                "No proof-of-delivery photo is on record for this shipment.",
                "لا توجد صورة إثبات تسليم مسجلة لهذه الشحنة.",
              )}
            </p>
          )}
        </section>
      )}
      <div className="order-secondary">
        <Fold
          id="finding"
          title={t("Finding / likely cause", "النتيجة / السبب المرجح")}
          summary={
            cause && cause.status !== "none"
              ? cause.status === "accepted"
                ? t("Accepted by the review", "قبلته المراجعة")
                : t("Hypothesis · not accepted", "فرضية · غير مقبولة")
              : t("No conclusion", "لا استنتاج")
          }
        >
          <p>
            {say(line("finding")?.text_en, line("finding")?.text_ar) ||
              say(cause?.text_en, cause?.text_ar)}
          </p>
          {review && review.status !== "not_reviewed" && (
            <p>
              {say(line("review")?.text_en, line("review")?.text_ar) ||
                say(review.text_en, review.text_ar)}
            </p>
          )}
          {cause?.confidence && (
            <p className="muted">
              {t(
                "The model's own stated confidence",
                "الثقة التي صرّح بها النموذج",
              )}
              : {cause.confidence}
            </p>
          )}
          {review?.reason_original && (
            <blockquote dir="ltr">
              <small>
                {t("The reviewer's own words", "كلام المراجع نفسه")}
              </small>
              {review.reason_original}
            </blockquote>
          )}
        </Fold>
        <Fold
          id="action"
          title={t("Action taken", "الإجراء المتخذ")}
          summary={
            currentAction
              ? t(...actionLabel(currentAction))
              : action && !lifecycle
                ? say(action.label_en, action.label_ar)
                : t("Nothing sent", "لم يُرسل شيء")
          }
        >
          <p>
            {currentAction
              ? t(...actionLabel(currentAction))
              : lifecycle
                ? t(
                    "No operational action is recorded.",
                    "لا إجراء تشغيلياً مسجلاً.",
                  )
                : say(line("action")?.text_en, line("action")?.text_ar)}
          </p>
          {brief.policy && brief.policy.decision !== "none" && (
            <p className="muted">
              {say(brief.policy.text_en, brief.policy.text_ar)}
            </p>
          )}
        </Fold>
        <Fold
          id="evidence"
          title={t("Supporting evidence", "الأدلة الداعمة")}
          summary={t(
            `${evidence.length} cited`,
            `${evidence.length} مستشهد بها`,
          )}
        >
          {evidence.length ? (
            <ul className="order-evidence">
              {evidence.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onEvidence(item.id)}
                    disabled={!item.in_graph}
                    title={
                      item.in_graph
                        ? undefined
                        : t("Not drawn in the graph", "غير مرسوم في الرسم")
                    }
                  >
                    <span dir="ltr">{item.id}</span>
                    {say(item.label_en, item.label_ar)}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              {t(
                "No cited evidence is recorded.",
                "لا توجد أدلة مستشهد بها مسجلة.",
              )}
            </p>
          )}
        </Fold>
        <Fold
          id="complete"
          title={t("Completion requirements", "متطلبات الإكمال")}
          summary={
            resolved
              ? t("Verified", "تم التحقق")
              : awaiting
                ? say(awaiting.text_en, awaiting.text_ar)
                : t("Verifier decides", "يقرر المتحقق")
          }
        >
          {resolved ? (
            <p>
              {say(brief.verification?.text_en, brief.verification?.text_ar)}
            </p>
          ) : (
            <>
              {awaiting && (
                <p>
                  {t("Awaited", "المنتظر")}:{" "}
                  {say(awaiting.text_en, awaiting.text_ar)}
                  {(action?.deadline_text_en || action?.deadline_at) &&
                    ` · ${say(action?.deadline_text_en, action?.deadline_text_ar) || dateTimeLabel(action!.deadline_at!)}`}
                </p>
              )}
              {missing.length > 0 && (
                <ul>
                  {missing.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              <p className="muted">
                <ShieldCheck size={12} />{" "}
                {t(
                  "The case is resolved only when the independent verifier confirms it from evidence recorded after the action. A new scan alone does not resolve it.",
                  "لا تُحل الحالة إلا عندما يؤكد المتحقق المستقل ذلك من أدلة سُجلت بعد الإجراء. المسح الجديد وحده لا يحلها.",
                )}
              </p>
            </>
          )}
        </Fold>
        <Fold id="technical" title={t("Technical record", "السجل التقني")}>
          <p className="muted technical" dir="ltr">
            {[
              brief.technical?.workflow_state,
              brief.technical?.authority_rule_id,
              brief.technical?.review_verdict,
              brief.technical?.run_id,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </Fold>
      </div>
    </article>
  );
}
