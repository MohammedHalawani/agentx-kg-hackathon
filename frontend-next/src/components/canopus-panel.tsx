import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion } from "motion/react";
import {
  ArrowRight,
  Ellipsis,
  Maximize2,
  Minimize2,
  Minus,
  Sparkles,
  AlertTriangle,
  Undo2,
  X,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { ConversationTranscript } from "@/components/conversation-transcript";
import { ChatComposer } from "@/components/chat-composer";
import { CaseActivityMarkers } from "@/components/activity-panel";
import { SelectControl } from "@/components/select-control";
import { useCanopus } from "@/state/canopus";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { ChatParticipant } from "@/domain/chat";
import { LAB, asset } from "@/config";
import { displayId } from "@/domain/case-view";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

const screenLabels = {
  operations: ["Operations", "العمليات"],
  investigation: ["Investigation", "التحقيق"],
  decisions: ["Decisions", "القرارات"],
  explore: ["Explore", "استكشاف"],
  audit: ["Audit", "التدقيق"],
  settings: ["Settings", "الإعدادات"],
} as const;
export function CanopusPanel() {
  const canopus = useCanopus();
  const {
    panelContext: context,
    panelOpen: open,
    presentation,
    connected,
  } = canopus;
  const { cases } = useOperations();
  const { t, preferences } = usePreferences();
  const systemReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const reduced = preferences.motion === "reduce" || systemReducedMotion;
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [visited, setVisited] = useState(false);
  const lastMode = useRef<"floating" | "expanded">("floating");
  if (open)
    lastMode.current = presentation === "expanded" ? "expanded" : "floating";
  const launcherRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const wasOpen = useRef(false);
  const titleId = useId(),
    descriptionId = useId(),
    panelId = useId();
  const key = context.caseId ?? `screen:${context.screen}`;
  const input = drafts[key] ?? "";
  const thread = canopus.thread(context);
  const selected = cases.find((c) => c.id === context.caseId);
  const expanded = presentation === "expanded";
  const close = canopus.close;
  useEffect(() => {
    if (open) setVisited(true);
    if (open !== wasOpen.current) {
      wasOpen.current = open;
      const frame = requestAnimationFrame(() => {
        if (open) {
          const editor =
            panelRef.current?.querySelector<HTMLTextAreaElement>("textarea");
          if (editor && !editor.disabled) editor.focus({ preventScroll: true });
          else panelRef.current?.focus({ preventScroll: true });
        } else launcherRef.current?.focus({ preventScroll: true });
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      // Nested shadcn selectors and mention menus consume their own Escape first.
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, close]);
  // Suggested questions belong to the lab's scripted assistant.
  const pageQuestions = !LAB_BUILD
    ? []
    : context.screen === "explore"
      ? [
          t(
            "Show shipments from Riyadh to Khobar.",
            "اعرض الشحنات من الرياض إلى الخبر.",
          ),
          t(
            "Highlight the selected shipment’s custody records.",
            "أبرز سجلات حيازة الشحنة المحددة.",
          ),
        ]
      : context.screen === "audit"
        ? [
            t(
              "Show all events for SHP-10482.",
              "اعرض كل الأحداث للشحنة SHP-10482.",
            ),
            t(
              "Show this month’s failed outcomes.",
              "اعرض النتائج التي فشل التحقق منها هذا الشهر.",
            ),
          ]
        : [];
  const questions = !LAB_BUILD
    ? []
    : pageQuestions.length
      ? pageQuestions
      : selected
        ? [
            t("Where is parcel custody confirmed?", "أين تأكدت حيازة الطرد؟"),
            t(
              "@reviewer why is approval required?",
              "@reviewer لماذا يلزم تفويض المشغل؟",
            ),
          ]
        : context.screen === "decisions"
          ? [
              t(
                "Which cases need human authority?",
                "ما الحالات التي تحتاج تفويضاً بشرياً؟",
              ),
              t(
                "Explain the review for SHP-10482.",
                "اشرح مراجعة الشحنة SHP-10482.",
              ),
            ]
          : [
              t(
                "What needs attention in the queue?",
                "ما الحالات التي تحتاج انتباهاً في القائمة؟",
              ),
              t(
                "What continues when investigation is paused?",
                "ما الذي يستمر عند إيقاف التحقيق مؤقتاً؟",
              ),
            ];
  function send(text: string, fail = false) {
    if (!connected || !text.trim() || thread.busy) return;
    const participant = text
      .match(/@(suhail|investigator|reviewer)\b/i)?.[1]
      ?.toLowerCase() as ChatParticipant | undefined;
    void canopus.send(context, text, participant ?? "suhail", fail);
    setDrafts((all) => ({ ...all, [key]: "" }));
  }
  return createPortal(
    <div
      className="canopus-layer"
      dir={preferences.language === "ar" ? "rtl" : "ltr"}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            ref={launcherRef}
            className="canopus-launcher"
            size="icon"
            aria-label={
              open
                ? t("Minimize Canopus assistant", "تصغير مساعد كانوبس")
                : t("Open Canopus assistant", "فتح مساعد كانوبس")
            }
            aria-expanded={open}
            aria-controls={visited || open ? panelId : undefined}
            aria-haspopup="dialog"
            onClick={() => (open ? close() : canopus.open())}
          >
            {open ? (
              <X size={21} aria-hidden="true" />
            ) : (
              <svg viewBox="0 0 40 40" aria-hidden="true">
                <path
                  d="M20 8l3.2 8.8L32 20l-8.8 3.2L20 32l-3.2-8.8L8 20l8.8-3.2z"
                  fill="currentColor"
                />
                <circle
                  cx="30"
                  cy="10"
                  r="2"
                  fill="currentColor"
                  opacity=".65"
                />
              </svg>
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={9}>
          {open
            ? t("Minimize Canopus", "تصغير كانوبس")
            : t("Ask Canopus", "اسأل كانوبس")}
        </TooltipContent>
      </Tooltip>
      {(visited || open) && (
        <motion.section
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          tabIndex={-1}
          aria-hidden={!open}
          inert={!open}
          data-presentation={lastMode.current}
          data-state={open ? "open" : "closed"}
          className="canopus-window"
          initial={{
            opacity: 0,
            scale: reduced ? 1 : 0.97,
            y: reduced ? 0 : 8,
          }}
          animate={{
            opacity: open ? 1 : 0,
            scale: !open && !reduced ? 0.97 : 1,
            y: !open && !reduced ? 8 : 0,
          }}
          transition={{
            duration: reduced ? 0 : 0.18,
            ease: [0.2, 0.7, 0.3, 1],
          }}
        >
          <header className="canopus-panel-header">
            <img src={asset("suhail.svg")} width="34" height="34" alt="" />
            <div className="canopus-heading">
              <h2 id={titleId}>Canopus</h2>
              <p id={descriptionId}>
                {connected
                  ? t("Suhail operations assistant", "مساعد سهيل للعمليات")
                  : t(
                      "Not connected · development preview",
                      "غير متصل · معاينة تطويرية",
                    )}
              </p>
            </div>
            <div className="canopus-panel-actions">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={
                      expanded
                        ? t(
                            "Collapse conversation workspace",
                            "تصغير مساحة المحادثة",
                          )
                        : t(
                            "Expand conversation workspace",
                            "توسيع مساحة المحادثة",
                          )
                    }
                    onClick={() =>
                      canopus.setPresentation(
                        expanded ? "floating" : "expanded",
                      )
                    }
                  >
                    {expanded ? (
                      <Minimize2 size={15} />
                    ) : (
                      <Maximize2 size={15} />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {expanded
                    ? t("Return to floating chat", "العودة إلى الدردشة العائمة")
                    : t("Expand conversation", "توسيع المحادثة")}
                </TooltipContent>
              </Tooltip>
              {LAB && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t(
                        "Canopus conversation options",
                        "خيارات محادثة كانوبس",
                      )}
                    >
                      <Ellipsis size={17} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      disabled={thread.busy}
                      onClick={() =>
                        send(
                          t(
                            "Explain the current operational context.",
                            "اشرح السياق التشغيلي الحالي.",
                          ),
                          true,
                        )
                      }
                    >
                      <AlertTriangle size={14} />
                      {t(
                        "Try a simulated response error",
                        "تجربة خطأ إجابة في المحاكاة",
                      )}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t(
                      "Minimize Canopus conversation",
                      "تصغير محادثة كانوبس",
                    )}
                    onClick={close}
                  >
                    <Minus size={17} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {t("Minimize conversation", "تصغير المحادثة")}
                </TooltipContent>
              </Tooltip>
            </div>
          </header>
          <div className="canopus-context">
            <span>
              {t(
                screenLabels[context.screen][0],
                screenLabels[context.screen][1],
              )}
            </span>
            <SelectControl
              label={t("Canopus shipment context", "سياق الشحنة في كانوبس")}
              value={context.caseId ?? "all"}
              onChange={(value) =>
                canopus.selectCase(value === "all" ? undefined : value)
              }
              options={[
                {
                  value: "all",
                  label: t("Workspace overview", "نظرة عامة على المساحة"),
                },
                ...cases.map((c) => ({ value: c.id, label: displayId(c) })),
              ]}
            />
          </div>
          <div className="canopus-transcript" key={key}>
            <ConversationTranscript
              messages={thread.messages}
              label={t("Canopus conversation transcript", "سجل محادثة كانوبس")}
              typing={
                thread.busy
                  ? (thread.activity ??
                    (LAB_BUILD
                      ? t(
                          "Preparing a synthetic response…",
                          "إعداد إجابة محاكاة…",
                        )
                      : t("Preparing a response…", "إعداد الإجابة…")))
                  : undefined
              }
              onRetry={(messageId) => void canopus.retry(context, messageId)}
              activity={selected && <CaseActivityMarkers c={selected} />}
              intro={
                <>
                  <div className="canopus-welcome">
                    <Sparkles size={19} />
                    <h3>
                      {!connected
                        ? t(
                            "Canopus is not connected yet.",
                            "كانوبس غير متصل بعد.",
                          )
                        : selected
                          ? t("Let’s follow the evidence.", "لنتتبع الأدلة.")
                          : t("How can I help?", "كيف يمكنني مساعدتك؟")}
                    </h3>
                    <p>
                      {connected
                        ? t(
                            "Understand evidence, decisions, and outcomes. Or ask me to find what matters on this page.",
                            "افهم الأدلة والقرارات والنتائج، أو اطلب مني العثور على ما يهمك في هذه الصفحة.",
                          )
                        : t(
                            "This conversation interface is in place, but Canopus has no backend yet, so it cannot answer and nothing is generated here. The recorded evidence, review, decisions and outcomes are on the case, Decisions and Audit screens.",
                            "واجهة المحادثة جاهزة، لكن كانوبس بلا خادم بعد، فلا يستطيع الإجابة ولا يُولَّد شيء هنا. الأدلة والمراجعة والقرارات والنتائج المسجلة في شاشات الحالة والقرارات والتدقيق.",
                          )}
                    </p>
                  </div>
                  <div className="suggested-questions">
                    {(connected ? questions : []).map((question) => (
                      <Button
                        variant="outline"
                        key={question}
                        onClick={() => send(question)}
                      >
                        {question}
                        <ArrowRight size={12} />
                      </Button>
                    ))}
                  </div>
                </>
              }
            />
          </div>
          {canopus.canUndo && (
            <div className="canopus-applied">
              <span>{t("Page filters updated", "تم تحديث التصفية")}</span>
              <Button variant="ghost" size="sm" onClick={canopus.undoFilters}>
                <Undo2 size={12} />
                {t("Undo filters", "تراجع عن التصفية")}
              </Button>
            </div>
          )}
          <footer className="canopus-compose-area">
            <ChatComposer
              value={input}
              onChange={(value) =>
                setDrafts((all) => ({ ...all, [key]: value }))
              }
              onSend={send}
              disabled={thread.busy || !connected}
              label={t("Ask Canopus", "اسأل كانوبس")}
              placeholder={
                connected
                  ? t(
                      "Ask Canopus, or mention @reviewer…",
                      "اسأل كانوبس، أو اذكر @reviewer…",
                    )
                  : t(
                      "Canopus is not connected to a backend yet.",
                      "كانوبس غير متصل بخادم بعد.",
                    )
              }
            />
            <div className="chat-readonly">
              {LAB_BUILD
                ? t(
                    "Synthetic replies · local simulation",
                    "إجابات اصطناعية · محاكاة محلية",
                  )
                : connected
                  ? t("Suhail operations assistant", "مساعد سهيل للعمليات")
                  : t(
                      "Not connected · no AI responses are generated",
                      "غير متصل · لا تُولَّد إجابات ذكاء اصطناعي",
                    )}
            </div>
          </footer>
        </motion.section>
      )}
    </div>,
    document.body,
  );
}
