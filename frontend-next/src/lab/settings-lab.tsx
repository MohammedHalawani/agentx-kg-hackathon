import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FlaskConical, Plus, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { usePreferences } from "@/state/preferences";
import { useCanopus } from "@/state/canopus";
import { useOperations } from "@/state/operations";
import { scenarioInfo, initialSnapshot } from "@/data/fixtures";
import { SelectControl } from "@/components/select-control";
import type { Scenario } from "@/domain/types";

/** Lab builds only: add or reset fixture cases in the browser. Never part of the connected product. */
export function LabSettings() {
  const canopus = useCanopus();
  const { t } = usePreferences();
  const { service } = useOperations();
  const navigate = useNavigate();
  const [scenario, setScenario] = useState<Scenario>("barcode");
  const [reset, setReset] = useState(false);
  return (
    <>
      <section className="surface settings-section simulation-settings">
        <div className="settings-heading">
          <FlaskConical size={18} />
          <div>
            <h2>{t("Local simulation", "المحاكاة المحلية")}</h2>
            <p>
              {t(
                "Test operational scenarios inside this isolated UI lab.",
                "اختبر السيناريوهات التشغيلية في مختبر الواجهة المستقل.",
              )}
            </p>
          </div>
          <span className="micro-tag">{t("LAB ONLY", "المختبر فقط")}</span>
        </div>
        <div className="setting-row">
          <div>
            <b>{t("Add a synthetic case", "إضافة حالة محاكاة")}</b>
            <p>
              {t(
                "The new case enters the incoming queue with a current timestamp.",
                "تدخل الحالة الجديدة إلى قائمة الوارد بوقت حالي.",
              )}
            </p>
          </div>
          <div className="simulation-add">
            <SelectControl
              label="Simulation scenario"
              value={scenario}
              onChange={(value) => setScenario(value as Scenario)}
              options={Object.entries(scenarioInfo).map(([value, s]) => ({
                value,
                label: s.issue,
              }))}
            />
            <Button
              size="sm"
              onClick={() => {
                const id = service.addCase(scenario);
                toast.info(
                  `${id} ${t("added to the queue", "أُضيفت إلى القائمة")}`,
                  {
                    action: {
                      label: t("Open case", "فتح الحالة"),
                      onClick: () => navigate(`/cases/${id}`),
                    },
                  },
                );
              }}
            >
              <Plus size={14} />
              {t("Add case", "إضافة حالة")}
            </Button>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <b>{t("Reset simulation", "إعادة المحاكاة")}</b>
            <p>
              {t(
                `Restore ${initialSnapshot().cases.length} synthetic cases and the seed history. Clears local changes and operator decisions.`,
                `استعادة ${initialSnapshot().cases.length} حالات المحاكاة والسجل الأصلي. يمسح التغييرات والقرارات المحلية.`,
              )}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setReset(true)}>
            <RotateCcw size={14} />
            {t("Reset lab", "إعادة المختبر")}
          </Button>
        </div>
      </section>
      <AlertDialog open={reset} onOpenChange={setReset}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t(
                "Reset the local simulation?",
                "إعادة تعيين المحاكاة المحلية؟",
              )}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t(
                "This restores the original synthetic cases and clears local decisions, activity, and case outcomes. Interface preferences are preserved.",
                "سيؤدي ذلك إلى استعادة حالات المحاكاة الأصلية ومسح القرارات والنشاط والنتائج المحلية. تُحفظ تفضيلات الواجهة.",
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("Cancel", "إلغاء")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                service.reset();
                canopus.clear();
                sessionStorage.removeItem("suhail-ui-lab.chat");
                toast.info(
                  t(
                    "Local simulation restored",
                    "تمت استعادة المحاكاة المحلية",
                  ),
                );
              }}
            >
              {t("Reset simulation", "إعادة المحاكاة")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
