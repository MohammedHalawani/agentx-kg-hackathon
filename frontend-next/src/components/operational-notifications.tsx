import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { displayId } from "@/domain/case-view";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

/**
 * Notifications reflect observed state changes, never a speculative outcome: the lab's own
 * mock transitions, or changes the backend reported between two reads of the queue.
 */
export function OperationalNotifications() {
  const { cases, events, backend: fromBackend, connection } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const primed = useRef(false);
  const { t } = usePreferences();
  const navigate = useNavigate();
  const previous = useRef(new Map(cases.map((c) => [c.id, c.status])));
  const previousEvent = useRef(events[0]?.id);
  useEffect(() => {
    const changed = cases.filter(
      (c) => previous.current.get(c.id) !== c.status,
    );
    previous.current = new Map(cases.map((c) => [c.id, c.status]));
    const newEvent = events[0]?.id;
    const localChange =
      newEvent !== previousEvent.current && newEvent?.startsWith("evt-");
    previousEvent.current = newEvent;
    if (backend) {
      // The first read of the queue is the starting point, not a set of changes.
      if (!primed.current) {
        if (connection?.lastSyncAt) primed.current = true;
        return;
      }
    } else if (!localChange) return;
    for (const c of changed) {
      const id = displayId(c);
      const options = {
        description: c.issue,
        action: {
          label: t("Open case", "فتح الحالة"),
          onClick: () => navigate(`/cases/${c.id}`),
        },
      };
      if (c.status === "investigating")
        toast.info(
          backend
            ? t(`${id} · investigation started`, `${id} · بدأ التحقيق`)
            : t(
                `${c.id} · simulated investigation started`,
                `${c.id} · بدأ التحقيق المحاكى`,
              ),
          options,
        );
      if (c.status === "executing")
        toast.info(
          t(`${id} · action authorized`, `${id} · تم تفويض الإجراء`),
          {
            ...options,
            description: t(
              "Execution and independent verification will follow.",
              "سيتبعه التنفيذ والتحقق المستقل.",
            ),
          },
        );
      if (c.status === "human_review")
        toast.warning(
          t(`${id} · human review required`, `${id} · يتطلب مراجعة بشرية`),
          options,
        );
      if (c.status === "needs_evidence")
        toast.warning(
          t(
            `${id} · additional evidence requested`,
            `${id} · طُلبت أدلة إضافية`,
          ),
          options,
        );
      if (c.status === "verifying")
        toast.warning(
          t(
            `${id} · outcome verification pending`,
            `${id} · التحقق من النتيجة معلق`,
          ),
          options,
        );
      if (c.status === "escalated") {
        if (c.outcome?.successful === false)
          toast.error(
            t(
              `${id} · outcome verification failed`,
              `${id} · فشل التحقق من النتيجة`,
            ),
            {
              ...options,
              description: t(
                "The case remains unresolved.",
                "تبقى الحالة غير محلولة.",
              ),
            },
          );
        else
          toast.info(
            t(`${id} · case escalated`, `${id} · تم تصعيد الحالة`),
            options,
          );
      }
      if (c.status === "resolved" && c.outcome?.successful)
        toast.success(
          t(
            `Shipment ${id} resolved — outcome verified.`,
            `حُلت الشحنة ${id} — تم التحقق من النتيجة.`,
          ),
          { ...options, duration: 8000 },
        );
    }
  }, [cases, events, navigate, t, backend, connection?.lastSyncAt]);
  return null;
}
