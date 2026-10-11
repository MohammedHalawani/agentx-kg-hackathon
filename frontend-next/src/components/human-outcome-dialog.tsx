import { useState } from "react";
import { AlertTriangle, ArrowRight, ClipboardCheck } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { SelectControl } from "@/components/select-control";
import type { HumanOutcomeType, OperationalCase } from "@/domain/types";
import { displayId } from "@/domain/case-view";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";

const OUTCOMES: [HumanOutcomeType, string, string][] = [
  ["parcel_located", "Parcel located", "تم العثور على الطرد"],
  [
    "delivered_confirmed_by_person",
    "Delivery confirmed by a person",
    "أكد شخص التسليم",
  ],
  ["returned_to_depot", "Returned to depot", "أُعيد إلى المستودع"],
  ["data_corrected", "Record corrected", "صُحح السجل"],
  ["parcel_not_found", "Parcel not found", "لم يُعثر على الطرد"],
];

/**
 * A person's finding after a physical or administrative check, sent to the backend's
 * human-outcome endpoint. The backend records it as human-verified (kept apart from
 * evidence-verified outcomes) and decides the case's state; "parcel not found" does not
 * resolve the case. Backend cases only.
 */
export function HumanOutcomeDialog({
  c,
  onClose,
}: {
  c: OperationalCase | null;
  onClose: () => void;
}) {
  const { service } = useOperations();
  const { t } = usePreferences();
  const [outcome, setOutcome] = useState<HumanOutcomeType>("parcel_located");
  const [finding, setFinding] = useState("");
  const [cited, setCited] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const evidence = (c?.evidence ?? []).filter(
    (e) => !e.id.startsWith("planned:"),
  );
  function close() {
    setFinding("");
    setCited([]);
    setError("");
    onClose();
  }
  async function submit() {
    if (!c || sending || !service.recordHumanOutcome) return;
    setSending(true);
    try {
      await service.recordHumanOutcome(c.id, {
        outcomeType: outcome,
        finding: finding.trim(),
        evidenceIds: cited,
      });
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }
  return (
    <Dialog open={!!c} onOpenChange={(open) => !open && close()}>
      <DialogContent className="decision-dialog">
        <DialogHeader>
          <DialogTitle>
            {t("Record a person's finding", "تسجيل نتيجة فحص بشري")}
          </DialogTitle>
          <DialogDescription>
            {c ? displayId(c) : ""} ·{" "}
            {t(
              "Recorded as human-verified, apart from evidence-verified outcomes.",
              "تُسجل كتحقق بشري، منفصلة عن النتائج المتحقق منها بالأدلة.",
            )}
          </DialogDescription>
        </DialogHeader>
        {c && (
          <>
            <div className="proposed-action">
              <ClipboardCheck size={20} />
              <div>
                <small>{t("WHAT THE PERSON FOUND", "ما وجده الشخص")}</small>
                <SelectControl
                  label="Human outcome type"
                  value={outcome}
                  onChange={(value) => setOutcome(value as HumanOutcomeType)}
                  options={OUTCOMES.map(([value, en, ar]) => ({
                    value,
                    label: t(en, ar),
                  }))}
                />
              </div>
            </div>
            <label className="field-label" htmlFor="human-finding">
              {t("Finding", "النتيجة")}
            </label>
            <Textarea
              id="human-finding"
              placeholder={t(
                "What was checked, where, and what was found (10 to 1000 characters)…",
                "ما الذي فُحص وأين وماذا وُجد (10 إلى 1000 حرف)…",
              )}
              value={finding}
              onChange={(e) => setFinding(e.target.value)}
              rows={3}
            />
            <div className="decision-outcome">
              <b>{t("Evidence this finding refers to", "الأدلة المرتبطة بالنتيجة")}</b>
              <div className="human-evidence">
                {evidence.map((e) => (
                  <label key={e.id} className="layer-option">
                    <Checkbox
                      checked={cited.includes(e.id)}
                      onCheckedChange={(checked) =>
                        setCited((all) =>
                          checked === true
                            ? [...all, e.id]
                            : all.filter((id) => id !== e.id),
                        )
                      }
                    />
                    <span>
                      {e.label}
                      <small>
                        {e.facility} · {e.time}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
              <span>
                <AlertTriangle size={13} />
                {outcome === "parcel_not_found"
                  ? t(
                      "A parcel that was not found is recorded; it does not resolve the case.",
                      "يُسجل عدم العثور على الطرد ولا يحل الحالة.",
                    )
                  : t(
                      "The backend decides the case's state from this record.",
                      "يحدد الخادم حالة الحالة من هذا السجل.",
                    )}
              </span>
            </div>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="dialog-actions">
              <Button variant="outline" onClick={close}>
                {t("Cancel", "إلغاء")}
              </Button>
              <Button
                onClick={submit}
                disabled={
                  sending || finding.trim().length < 10 || cited.length === 0
                }
              >
                {t("Record finding", "تسجيل النتيجة")}
                <ArrowRight size={14} />
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
