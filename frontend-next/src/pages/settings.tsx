import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Sun,
  Moon,
  Globe2,
  SlidersHorizontal,
  FlaskConical,
  Plus,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
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
import { PageTitle } from "@/components/shared";
import { usePreferences } from "@/state/preferences";
import { useCanopus, useCanopusScreen } from "@/state/canopus";
import { useOperations } from "@/state/operations";
import { scenarioInfo, initialSnapshot } from "@/data/fixtures";
import { SelectControl } from "@/components/select-control";
import type { Scenario } from "@/domain/types";
export function SettingsPage() {
  const canopus = useCanopus();
  useCanopusScreen({ screen: "settings" });
  const { preferences, update, t } = usePreferences();
  const { service, cases, events } = useOperations();
  const navigate = useNavigate();
  const [scenario, setScenario] = useState<Scenario>("barcode");
  const [reset, setReset] = useState(false);
  return (
    <>
      <PageTitle
        title={t("Settings", "الإعدادات")}
        description={t(
          "Make the workspace work for you.",
          "خصص مساحة العمل لتناسب احتياجاتك.",
        )}
      />
      <div className="settings-layout">
        <div className="settings-sections">
          <section className="surface settings-section">
            <div className="settings-heading">
              <Sun size={18} />
              <div>
                <h2>{t("Appearance", "المظهر")}</h2>
                <p>
                  {t(
                    "Choose a comfortable view for your working environment.",
                    "اختر مظهراً مريحاً لبيئة عملك.",
                  )}
                </p>
              </div>
            </div>
            <div className="setting-row">
              <div>
                <b>{t("Interface theme", "مظهر الواجهة")}</b>
                <p>
                  {t(
                    "Applied throughout the map, graph, and workspace.",
                    "يُطبق في الخريطة والرسم ومساحة العمل.",
                  )}
                </p>
              </div>
              <div className="theme-options">
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Light theme"
                  aria-pressed={preferences.theme === "light"}
                  onClick={() => update({ theme: "light" })}
                >
                  <Sun size={16} />
                  {t("Light", "فاتح")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Dark theme"
                  aria-pressed={preferences.theme === "dark"}
                  onClick={() => update({ theme: "dark" })}
                >
                  <Moon size={16} />
                  {t("Dark", "داكن")}
                </Button>
              </div>
            </div>
            <div className="setting-row">
              <div>
                <b>{t("Compact tables", "جداول مدمجة")}</b>
                <p>
                  {t(
                    "Show more operational rows in the same space.",
                    "عرض المزيد من الصفوف في المساحة نفسها.",
                  )}
                </p>
              </div>
              <Switch
                aria-label="Compact tables"
                checked={preferences.density === "compact"}
                onCheckedChange={(v) =>
                  update({ density: v ? "compact" : "comfortable" })
                }
              />
            </div>
          </section>
          <section className="surface settings-section">
            <div className="settings-heading">
              <Globe2 size={18} />
              <div>
                <h2>{t("Language & region", "اللغة والمنطقة")}</h2>
                <p>
                  {t(
                    "English and Arabic with native right-to-left navigation.",
                    "الإنجليزية والعربية مع تنقل أصلي من اليمين إلى اليسار.",
                  )}
                </p>
              </div>
            </div>
            <div className="setting-row">
              <div>
                <b>{t("Interface language", "لغة الواجهة")}</b>
                <p>
                  {t(
                    "Navigation and controls are localized. Synthetic evidence remains in English.",
                    "التنقل وعناصر التحكم مترجمة. تبقى أدلة المحاكاة بالإنجليزية.",
                  )}
                </p>
              </div>
              <SelectControl
                label="Interface language"
                value={preferences.language}
                onChange={(value) => update({ language: value as "en" | "ar" })}
                options={[
                  { value: "en", label: "English" },
                  { value: "ar", label: "العربية" },
                ]}
              />
            </div>
            <div className="setting-row">
              <div>
                <b>{t("Operational timezone", "المنطقة الزمنية التشغيلية")}</b>
                <p>
                  {t(
                    "Shipment observations and audit events use Saudi time.",
                    "تستخدم ملاحظات الشحنات والأحداث توقيت السعودية.",
                  )}
                </p>
              </div>
              <span className="date-pill">Asia/Riyadh · UTC+03:00</span>
            </div>
          </section>
          <section className="surface settings-section">
            <div className="settings-heading">
              <SlidersHorizontal size={18} />
              <div>
                <h2>{t("Interaction preferences", "تفضيلات التفاعل")}</h2>
                <p>
                  {t(
                    "Keep movement purposeful and comfortable.",
                    "اجعل الحركة هادفة ومريحة.",
                  )}
                </p>
              </div>
            </div>
            <div className="setting-row">
              <div>
                <b>{t("Reduce motion", "تقليل الحركة")}</b>
                <p>
                  {t(
                    "System preferences are also respected automatically.",
                    "تُحترم تفضيلات النظام أيضاً بشكل تلقائي.",
                  )}
                </p>
              </div>
              <Switch
                aria-label="Reduce motion"
                checked={preferences.motion === "reduce"}
                onCheckedChange={(v) =>
                  update({ motion: v ? "reduce" : "system" })
                }
              />
            </div>
            <div className="setting-row">
              <div>
                <b>
                  {t("Default investigation layout", "تخطيط التحقيق الافتراضي")}
                </b>
                <p>
                  {t(
                    "The map and knowledge graph stay together on desktop.",
                    "تظل الخريطة والرسم المعرفي معاً على سطح المكتب.",
                  )}
                </p>
              </div>
              <span className="date-pill">
                {t("Balanced · side by side", "متوازن · جنباً إلى جنب")}
              </span>
            </div>
          </section>
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
              <Button
                variant="outline"
                size="sm"
                onClick={() => setReset(true)}
              >
                <RotateCcw size={14} />
                {t("Reset lab", "إعادة المختبر")}
              </Button>
            </div>
          </section>
        </div>
        <aside className="settings-aside surface">
          <span className="settings-shield">
            <ShieldCheck size={24} />
          </span>
          <h3>{t("An isolated workspace", "مساحة عمل مستقلة")}</h3>
          <p>
            {t(
              "This UI lab uses a typed mock operations service. It does not connect to FastAPI, Neo4j, Ollama, or the original Suhail database.",
              "يستخدم هذا المختبر خدمة عمليات محاكاة ذات أنواع محددة. لا يتصل بخدمات FastAPI أو Neo4j أو Ollama أو قاعدة سهيل الأصلية.",
            )}
          </p>
          <div>
            <small>{t("CURRENT STATE", "الحالة الحالية")}</small>
            <b>
              {cases.length} {t("cases", "حالات")} · {events.length}{" "}
              {t("events", "أحداث")}
            </b>
          </div>
          <p className="small-print">
            {t(
              "Case state and preferences are saved in this browser. Chat history is retained for this browser session.",
              "تُحفظ الحالات والتفضيلات في هذا المتصفح. يُحفظ سجل الدردشة لجلسة المتصفح الحالية.",
            )}
          </p>
        </aside>
      </div>
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
