import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";

/** Notifications reflect observed mock-state changes, never a speculative outcome. */
export function OperationalNotifications() {
  const { cases, events } = useOperations();
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
    if (!localChange) return;
    for (const c of changed) {
      const options = {
        description: c.issue,
        action: {
          label: t("Open case", "فتح الحالة"),
          onClick: () => navigate(`/cases/${c.id}`),
        },
      };
      if (c.status === "investigating")
        toast.info(
          t(
            `${c.id} · simulated investigation started`,
            `${c.id} · بدأ التحقيق المحاكى`,
          ),
          options,
        );
      if (c.status === "executing")
        toast.info(
          t(`${c.id} · action authorized`, `${c.id} · تم تفويض الإجراء`),
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
          t(`${c.id} · human review required`, `${c.id} · يتطلب مراجعة بشرية`),
          options,
        );
      if (c.status === "needs_evidence")
        toast.warning(
          t(
            `${c.id} · additional evidence requested`,
            `${c.id} · طُلبت أدلة إضافية`,
          ),
          options,
        );
      if (c.status === "verifying")
        toast.warning(
          t(
            `${c.id} · outcome verification pending`,
            `${c.id} · التحقق من النتيجة معلق`,
          ),
          options,
        );
      if (c.status === "escalated") {
        if (c.outcome?.successful === false)
          toast.error(
            t(
              `${c.id} · outcome verification failed`,
              `${c.id} · فشل التحقق من النتيجة`,
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
            t(`${c.id} · case escalated`, `${c.id} · تم تصعيد الحالة`),
            options,
          );
      }
      if (c.status === "resolved" && c.outcome?.successful)
        toast.success(
          t(
            `Shipment ${c.id} resolved — outcome verified.`,
            `حُلت الشحنة ${c.id} — تم التحقق من النتيجة.`,
          ),
          { ...options, duration: 8000 },
        );
    }
  }, [cases, events, navigate, t]);
  return null;
}
