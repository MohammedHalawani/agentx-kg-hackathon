import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowUp, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  answerOps,
  parseOpsRequest,
  type OpsAnswer,
} from "@/domain/operations-assistant";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import {
  applyOpsView,
  clearOpsView,
  undoOpsView,
  useCanUndoOpsView,
} from "@/state/ops-view";

/** One request about the queue and the rule-based reply. Browser memory only. */
interface Turn {
  id: string;
  request: string;
  answer: OpsAnswer;
}
let turns: Turn[] = [];
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const useTurns = () =>
  useSyncExternalStore(
    subscribe,
    () => turns,
    () => turns,
  );
// eslint-disable-next-line react-refresh/only-export-components
export const useOpsTurnCount = () => useTurns().length;

const SUGGESTED: [string, string][] = [
  ["Show the five most urgent cases", "اعرض أكثر خمس حالات إلحاحاً"],
  ["Which cases are overdue?", "ما الحالات المتأخرة؟"],
  ["Filter to barcode problems", "صفِّ إلى مشكلات الباركود"],
  [
    "Which cases need immediate human attention?",
    "ما الحالات التي تحتاج تدخلاً بشرياً فورياً؟",
  ],
];

/**
 * The Operations assistant's conversation. Each request is answered by fixed rules from the
 * loaded backend queue and, when it names a view, applies that view to the table, where it is
 * shown with Undo and Clear. No model is called and nothing is written anywhere.
 */
export function OperationsAskThread() {
  const { t, preferences } = usePreferences();
  const list = useTurns();
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [list.length]);
  if (!list.length) return null;
  const arabic = preferences.language === "ar";
  return (
    <section className="chat-thread" data-testid="operations-ask-thread">
      {list.map((turn) => (
        <div key={turn.id} className="chat-turn">
          <p className="chat-question">{turn.request}</p>
          <div className="chat-answer" data-testid="operations-answer">
            <div className="chat-prose" dir={arabic ? "rtl" : "ltr"}>
              <p>{arabic ? turn.answer.text[1] : turn.answer.text[0]}</p>
            </div>
            <div className="chat-meta">
              <span>
                {t(
                  "Suhail filter rules · loaded queue · no AI model used",
                  "قواعد التصفية في سهيل · القائمة المحملة · دون نموذج ذكاء اصطناعي",
                )}
              </span>
            </div>
          </div>
        </div>
      ))}
      <div ref={end} />
    </section>
  );
}

export function OperationsAskComposer() {
  const { cases } = useOperations();
  const { t } = usePreferences();
  const list = useTurns();
  const canUndo = useCanUndoOpsView();
  const [draft, setDraft] = useState("");
  const ask = (request: string) => {
    const text = request.trim().slice(0, 300);
    if (!text) return;
    const answer = answerOps(text, cases);
    if (answer.view) applyOpsView(answer.view, text);
    else if (parseOpsRequest(text).type === "clear")
      if (/undo|تراجع/i.test(text)) undoOpsView();
      else clearOpsView();
    turns = [
      ...turns,
      { id: `${Date.now()}-${turns.length}`, request: text, answer },
    ];
    listeners.forEach((listener) => listener());
    setDraft("");
  };
  return (
    <div className="chat-composer-area" data-testid="operations-ask">
      {list.length === 0 && (
        <div className="chat-suggested">
          {SUGGESTED.map(([en, ar]) => (
            <button key={en} type="button" onClick={() => ask(t(en, ar))}>
              {t(en, ar)}
            </button>
          ))}
        </div>
      )}
      {canUndo && list.length > 0 && (
        <div className="canopus-applied">
          <span>{t("Table view changed", "تغيّر عرض الجدول")}</span>
          <Button variant="ghost" size="sm" onClick={undoOpsView}>
            <Undo2 size={12} />
            {t("Undo", "تراجع")}
          </Button>
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          ask(draft);
        }}
      >
        <input
          aria-label={t(
            "Ask Canopus about the queue",
            "اسأل كانوبس عن القائمة",
          )}
          placeholder={t("Ask about the queue…", "اسأل عن القائمة…")}
          maxLength={300}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          type="submit"
          size="icon"
          disabled={!draft.trim()}
          aria-label={t("Send request", "إرسال الطلب")}
        >
          <ArrowUp size={14} />
        </Button>
      </form>
    </div>
  );
}
