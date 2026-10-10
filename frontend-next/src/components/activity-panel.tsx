import {
  AlertTriangle,
  CheckCircle2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Spinner } from "@/components/ui/spinner";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { stages, type OperationalCase } from "@/domain/types";
import { timeLabel } from "@/lib/dates";

/** The case activity survives in Canopus without a second floating chat dock. */
export function CaseActivityMarkers({ c }: { c: OperationalCase }) {
  const { events } = useOperations();
  const { t } = usePreferences();
  const active = ["investigating", "executing", "verifying"].includes(c.status);
  const waiting = ["human_review", "needs_evidence"].includes(c.status);
  const recent = events
    .filter((e) => e.caseId === c.id)
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
    .slice(0, 2)
    .reverse();
  return (
    <div className="case-conversation-markers">
      {(waiting ? [] : recent).map((event) => (
        <Marker key={event.id} className="conversation-marker">
          <MarkerIcon>
            {event.kind === "verification" &&
            c.outcome?.successful === false ? (
              <XCircle className="text-destructive size-3" />
            ) : (
              <CheckCircle2 className="text-success size-3" />
            )}
          </MarkerIcon>
          <MarkerContent>
            {event.title}
            <small>
              {timeLabel(event.timestamp)} · {t("simulated", "محاكاة")}
            </small>
          </MarkerContent>
        </Marker>
      ))}
      <Marker
        role={active ? "status" : undefined}
        className="conversation-marker"
      >
        <MarkerIcon>
          {active ? (
            <Spinner className="size-3" />
          ) : waiting ? (
            <AlertTriangle className="text-warning size-3" />
          ) : c.status === "escalated" ? (
            <XCircle className="text-destructive size-3" />
          ) : (
            <ShieldCheck className="size-3" />
          )}
        </MarkerIcon>
        <MarkerContent>
          {c.status === "human_review"
            ? t("Awaiting human decision", "بانتظار قرار بشري")
            : c.status === "needs_evidence"
              ? t("Additional evidence requested", "طُلبت أدلة إضافية")
              : c.status === "resolved"
                ? t(
                    "Outcome independently verified",
                    "تم التحقق المستقل من النتيجة",
                  )
                : c.status === "verifying"
                  ? t(
                      "Outcome verification pending",
                      "بانتظار التحقق من النتيجة",
                    )
                  : c.status === "escalated"
                    ? t(
                        "Recovery needs manual follow-up",
                        "تحتاج المعالجة متابعة بشرية",
                      )
                    : c.run
                      ? stages[c.run.stage].detail
                      : t(
                          "Ready for a simulated investigation",
                          "جاهز لتحقيق محاكى",
                        )}
        </MarkerContent>
      </Marker>
    </div>
  );
}
