import type { OperationalCase } from "@/domain/types";
import {
  actionLabel,
  verifiedResolution,
  waitingLabel,
} from "@/domain/investigation-workspace";
import { usePreferences } from "@/state/preferences";
import { dateTimeLabel } from "@/lib/dates";

export function ActionLifecycle({
  c,
  onEvidence,
}: {
  c: OperationalCase;
  onEvidence: (id: string) => void;
}) {
  const { t } = usePreferences();
  const status = c.backend?.actionStatus;
  if (!status) return null;
  const label = verifiedResolution(c)
    ? ["Shipment exception verified resolved", "تم التحقق من حل استثناء الشحنة"]
    : waitingLabel(c);
  return (
    <section
      className={`action-lifecycle ${verifiedResolution(c) ? "verified" : ""}`}
      data-testid="action-lifecycle"
    >
      <div className="section-heading compact">
        <h3>
          {t("Operational action & verification", "الإجراء التشغيلي والتحقق")}
        </h3>
        <small>{t("Synthetic", "اصطناعي")}</small>
      </div>
      <p role="status" data-testid="action-resolution">
        {t(label[0], label[1])}
      </p>
      {status.actions.map((action) => (
        <details key={action.execution_id} className="action-record">
          <summary>
            <b>{action.action_type.replaceAll("_", " ").toLowerCase()}</b>
            <span>{t(...actionLabel(action))}</span>
          </summary>
          <dl className="action-axes">
            {(
              [
                "authorization",
                "dispatch",
                "acknowledgement",
                "acceptance",
                "execution",
                "verification",
              ] as const
            ).map((axis) => (
              <div key={axis}>
                <dt>{axis}</dt>
                <dd>{action[axis].replaceAll("_", " ").toLowerCase()}</dd>
              </div>
            ))}
          </dl>
          <ol>
            {action.events.map((event) => (
              <li key={event.id} className={event.late ? "late" : ""}>
                <b>{event.kind.replaceAll("_", " ").toLowerCase()}</b>
                <time>{dateTimeLabel(event.occurred_at)}</time>
                {event.recorded_at !== event.occurred_at && (
                  <small>
                    {t("Received", "استُلم")} {dateTimeLabel(event.recorded_at)}
                  </small>
                )}
                {event.late && (
                  <small>
                    {t(
                      "Late / superseded · audit history only",
                      "متأخر أو متجاوز · سجل تدقيق فقط",
                    )}
                  </small>
                )}
                {event.source_ref && (
                  <small dir="ltr">{event.source_ref}</small>
                )}
                {event.rule_id && <small dir="ltr">{event.rule_id}</small>}
                {event.evidence_ids.map((id) => (
                  <button
                    key={id}
                    disabled={
                      !c.nodes.some((node) => node.id === id) &&
                      !c.evidence.some((item) => item.id === id)
                    }
                    title={t(
                      "Inspect this source if it is available in the current view",
                      "فحص المصدر إذا كان متاحاً في العرض الحالي",
                    )}
                    onClick={() => onEvidence(id)}
                    dir="ltr"
                  >
                    {id}
                  </button>
                ))}
              </li>
            ))}
          </ol>
        </details>
      ))}
      {status.actions.length > 0 && (
        <small>
          {t(
            "Acknowledgement and acceptance do not resolve the shipment. Verification may credit a qualifying independent routine read; it does not establish who performed that read.",
            "تأكيد الاستلام وقبول المهمة لا يحلان الشحنة. قد يعتمد التحقق قراءة روتينية مستقلة مؤهلة دون إثبات هوية من أجراها.",
          )}
        </small>
      )}
    </section>
  );
}
