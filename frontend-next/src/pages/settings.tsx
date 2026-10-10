import {
  Sun,
  Moon,
  Globe2,
  SlidersHorizontal,
  ShieldCheck,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { PageTitle } from "@/components/shared";
import { usePreferences } from "@/state/preferences";
import { useCanopusScreen } from "@/state/canopus";
import { useOperations } from "@/state/operations";
import { SelectControl } from "@/components/select-control";
import { dateTimeLabel } from "@/lib/dates";

// Lab builds only: the fixture simulation controls (null in the connected product).
import { LabSettings } from "@/services/lab-entry";
export function SettingsPage() {
  useCanopusScreen({ screen: "settings" });
  const { preferences, update, t } = usePreferences();
  const { cases, events, backend, connection } = useOperations();
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
          {LabSettings && <LabSettings />}
          {backend && (
            <section className="surface settings-section">
              <div className="settings-heading">
                <Server size={18} />
                <div>
                  <h2>{t("Backend connection", "الاتصال بالخادم")}</h2>
                  <p>
                    {t(
                      "What this workspace is reading. Cases, evidence, decisions and outcomes come from the Suhail backend.",
                      "ما تقرؤه مساحة العمل. الحالات والأدلة والقرارات والنتائج تأتي من خادم سهيل.",
                    )}
                  </p>
                </div>
                <span className="micro-tag">
                  {t("SYNTHETIC DATA", "بيانات اصطناعية")}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>{t("Connection", "الاتصال")}</b>
                  <p>
                    {connection?.error ??
                      t(
                        "Queue and worker status are re-read every few seconds.",
                        "تُعاد قراءة القائمة وحالة المعالجة كل بضع ثوانٍ.",
                      )}
                  </p>
                </div>
                <span className="date-pill">
                  {connection?.state === "online"
                    ? t("Connected", "متصل")
                    : connection?.state === "connecting"
                      ? t("Connecting…", "جارٍ الاتصال…")
                      : connection?.state === "degraded"
                        ? t("Connection interrupted", "انقطع الاتصال")
                        : t("Backend unreachable", "تعذر الوصول إلى الخادم")}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>{t("Dataset", "مجموعة البيانات")}</b>
                  <p>
                    {t(
                      "A synthetic logistics dataset. It is not SPL operational data.",
                      "مجموعة بيانات لوجستية اصطناعية. ليست بيانات تشغيلية لسبل.",
                    )}
                  </p>
                </div>
                <span className="date-pill" dir="ltr">
                  {connection?.database ?? "—"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>{t("Dataset clock", "ساعة البيانات")}</b>
                  <p>
                    {t(
                      "Evidence is visible up to this time. Audit records also carry their recording time.",
                      "تظهر الأدلة حتى هذا الوقت. تحمل سجلات التدقيق وقت تسجيلها أيضاً.",
                    )}
                  </p>
                </div>
                <span className="date-pill">
                  {connection?.asOf ? dateTimeLabel(connection.asOf) : "—"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>{t("Investigation worker", "معالج التحقيق")}</b>
                  <p>
                    {t(
                      "Controlled by the Auto switch on Operations. The backend processes the oldest eligible case first.",
                      "يتحكم به مفتاح التلقائي في العمليات. يعالج الخادم أقدم حالة مؤهلة أولاً.",
                    )}
                  </p>
                </div>
                <span className="date-pill">
                  {connection?.worker
                    ? `${connection.worker.state} · ${connection.worker.processedCount} ${t("processed", "تمت معالجتها")}`
                    : "—"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>{t("Operator session", "جلسة المشغل")}</b>
                  <p>
                    {connection?.controls === "unavailable"
                      ? t(
                          "The backend grants operator controls only to a local, same-origin page. This page can read but not decide.",
                          "يمنح الخادم صلاحيات المشغل لصفحة محلية من المصدر نفسه فقط. هذه الصفحة للقراءة دون قرار.",
                        )
                      : t(
                          "A local development session chosen by the backend. It is not production identity.",
                          "جلسة تطوير محلية يحددها الخادم. ليست هوية إنتاجية.",
                        )}
                  </p>
                </div>
                <span className="date-pill" dir="ltr">
                  {connection?.operator
                    ? `${connection.operator.actorId} · ${connection.operator.role}`
                    : "—"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <b>Canopus</b>
                  <p>
                    {t(
                      "The conversation interface is in place. Its backend does not exist yet, so it answers nothing.",
                      "واجهة المحادثة جاهزة. خادمها غير موجود بعد، لذا لا تجيب بشيء.",
                    )}
                  </p>
                </div>
                <span className="date-pill">
                  {t("Not connected", "غير متصل")}
                </span>
              </div>
            </section>
          )}
        </div>
        <aside className="settings-aside surface">
          <span className="settings-shield">
            <ShieldCheck size={24} />
          </span>
          <h3>
            {backend
              ? t("Connected to the Suhail backend", "متصل بخادم سهيل")
              : t("An isolated workspace", "مساحة عمل مستقلة")}
          </h3>
          <p>
            {backend
              ? t(
                  "Diagnosis, review, approval, execution and verification are decided by the backend. This page shows what it recorded and sends operator requests; it resolves nothing by itself.",
                  "التشخيص والمراجعة والموافقة والتنفيذ والتحقق يقررها الخادم. تعرض هذه الصفحة ما سجّله وترسل طلبات المشغل، ولا تحل شيئاً بنفسها.",
                )
              : t(
                  "This UI lab uses a typed mock operations service. It does not connect to FastAPI, Neo4j, Ollama, or the original Suhail database.",
                  "يستخدم هذا المختبر خدمة عمليات محاكاة ذات أنواع محددة. لا يتصل بخدمات FastAPI أو Neo4j أو Ollama أو قاعدة سهيل الأصلية.",
                )}
          </p>
          <div>
            <small>{t("CURRENT STATE", "الحالة الحالية")}</small>
            <b>
              {cases.length} {t("cases", "حالات")} · {events.length}{" "}
              {backend
                ? t("audit events loaded", "أحداث تدقيق محمّلة")
                : t("events", "أحداث")}
            </b>
          </div>
          <p className="small-print">
            {backend
              ? t(
                  "Only interface preferences are saved in this browser. Case state lives in the backend.",
                  "تُحفظ تفضيلات الواجهة فقط في هذا المتصفح. حالة الحالات محفوظة في الخادم.",
                )
              : t(
                  "Case state and preferences are saved in this browser. Chat history is retained for this browser session.",
                  "تُحفظ الحالات والتفضيلات في هذا المتصفح. يُحفظ سجل الدردشة لجلسة المتصفح الحالية.",
                )}
          </p>
        </aside>
      </div>
    </>
  );
}
