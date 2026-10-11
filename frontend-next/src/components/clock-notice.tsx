import { useState } from "react";
import { FastForward, PauseCircle, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { OperationalCase } from "@/domain/types";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";

/**
 * A case that is waiting for new evidence while the simulated clock is paused cannot move:
 * nothing arrives until time passes. This says so where the operator is looking and puts the
 * way out one click away. The paused state is the backend's own (its worker status).
 */
export function ClockNotice({ c }: { c: OperationalCase }) {
  const { service, connection } = useOperations();
  const { t } = usePreferences();
  const [working, setWorking] = useState<"" | "start" | "skip">("");
  const paused = connection?.clock && !connection.clock.running;
  const waiting = c.status === "verifying" || c.status === "executing";
  if (!c.backend || !paused || !waiting) return null;
  const run = (kind: "start" | "skip") => {
    setWorking(kind);
    const task =
      kind === "start"
        ? service.setClock!(true).then(() => undefined)
        : service.skipClock!().then((result) => {
            const hours = Math.round((result.simulatedMinutes / 60) * 10) / 10;
            toast.info(
              result.reason === "outcome_decided"
                ? t(`Skipped ${hours} hours: a result was verified.`, `تم تخطي ${hours} ساعة: تم التحقق من نتيجة.`)
                : result.reason === "case_opened"
                  ? t(`Skipped ${hours} hours: a new case opened.`, `تم تخطي ${hours} ساعة: فُتحت حالة جديدة.`)
                  : t(`Skipped ${hours} hours: nothing arrived yet.`, `تم تخطي ${hours} ساعة: لم يصل شيء بعد.`),
            );
          });
    void task
      .catch((error: Error) => toast.error(error.message))
      .finally(() => setWorking(""));
  };
  return (
    <div className="clock-notice" role="status" data-testid="clock-notice">
      <PauseCircle size={16} />
      <p>
        {t(
          "The simulated clock is paused, so no new evidence can arrive and this case cannot move.",
          "الساعة المحاكاة متوقفة، فلا يمكن أن تصل أدلة جديدة ولا تتقدم هذه الحالة.",
        )}
      </p>
      {service.setClock && (
        <Button size="sm" disabled={!!working} onClick={() => run("start")}>
          <Play size={12} />
          {t("Start the clock", "شغّل الساعة")}
        </Button>
      )}
      {service.skipClock && (
        <Button size="sm" variant="outline" disabled={!!working} onClick={() => run("skip")}>
          <FastForward size={12} />
          {working === "skip"
            ? t("Skipping…", "جارٍ التخطي…")
            : t("Skip to next event", "تخطَّ إلى الحدث التالي")}
        </Button>
      )}
    </div>
  );
}
