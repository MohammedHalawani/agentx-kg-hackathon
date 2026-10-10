import { useState } from "react";
import { ShieldCheck, ArrowRight, AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AuthorityDecision, OperationalCase } from "@/domain/types";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { displayId } from "@/domain/case-view";
export function DecisionDialog({
  c,
  verdict,
  onClose,
}: {
  c: OperationalCase | null;
  verdict: AuthorityDecision["verdict"];
  onClose: () => void;
}) {
  const { service, backend } = useOperations();
  const { t } = usePreferences();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  async function submit() {
    if (!c || sending) return;
    setSending(true);
    try {
      // Backend: the dialog stays open until the backend accepts or refuses the decision.
      await service.decide(c.id, verdict, reason);
      setReason("");
      setError("");
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }
  return (
    <Dialog
      open={!!c}
      onOpenChange={(open) => {
        if (!open) {
          setReason("");
          setError("");
          onClose();
        }
      }}
    >
      <DialogContent className="decision-dialog">
        <DialogHeader>
          <DialogTitle>
            {verdict === "approved"
              ? t("Authorize this action", "تفويض هذا الإجراء")
              : verdict === "rejected"
                ? t("Reject the proposed action", "رفض الإجراء المقترح")
                : t("Escalate this case", "تصعيد هذه الحالة")}
          </DialogTitle>
          <DialogDescription>
            {c ? displayId(c) : ""} ·{" "}
            {t(
              "Your decision will be recorded in the audit history.",
              "سيُسجل قرارك في سجل التدقيق.",
            )}
          </DialogDescription>
        </DialogHeader>
        {c && (
          <>
            <div className="proposed-action">
              <ShieldCheck size={20} />
              <div>
                <small>{t("PROPOSED ACTION", "الإجراء المقترح")}</small>
                <h3>{c.recommendation.title}</h3>
                <p>{c.recommendation.detail}</p>
              </div>
            </div>
            <div className="decision-outcome">
              <b>{t("Expected verification", "التحقق المتوقع")}</b>
              <p>{c.recommendation.expectedOutcome}</p>
              <span>
                <AlertTriangle size={13} />
                {t(
                  "Authorization alone does not resolve this case.",
                  "التفويض وحده لا يحل هذه الحالة.",
                )}
              </span>
            </div>
            <label className="field-label" htmlFor="decision-reason">
              {t("Decision reason", "سبب القرار")}
            </label>
            <Textarea
              id="decision-reason"
              placeholder={t(
                "Explain the evidence supporting your decision…",
                "اشرح الأدلة التي تدعم قرارك…",
              )}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              disabled={backend}
            />
            {backend && (
              <p className="text-xs text-muted-foreground">
                {t(
                  "The backend does not store decision reasons yet, so none is collected here. The decision, operator and time are audited.",
                  "لا يخزن الخادم أسباب القرارات بعد، لذا لا يُجمع سبب هنا. يُدقق القرار والمشغل والوقت.",
                )}
              </p>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="dialog-actions">
              <Button
                variant="outline"
                onClick={() => {
                  setReason("");
                  setError("");
                  onClose();
                }}
              >
                {t("Cancel", "إلغاء")}
              </Button>
              <Button
                variant={verdict === "rejected" ? "destructive" : "default"}
                onClick={submit}
                disabled={sending || (!backend && !reason.trim())}
              >
                {verdict === "approved"
                  ? t("Authorize action", "تفويض الإجراء")
                  : verdict === "rejected"
                    ? t("Reject action", "رفض الإجراء")
                    : t("Escalate case", "تصعيد الحالة")}
                <ArrowRight size={14} />
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
