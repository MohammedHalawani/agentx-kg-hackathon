import { useState, useSyncExternalStore } from "react";
import {
  ArrowUp,
  Cpu,
  Network,
  Quote,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type {
  CanopusAnswer,
  CanopusOffer,
  OperationalCase,
} from "@/domain/types";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";

/** One exchange about a case. Kept in the browser only: the server stores nothing. */
interface Turn {
  id: string;
  question: string;
  answer?: CanopusAnswer;
  error?: string;
}
const store = new Map<string, Turn[]>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const EMPTY: Turn[] = [];
const useTurns = (caseId: string) =>
  useSyncExternalStore(
    subscribe,
    () => store.get(caseId) ?? EMPTY,
    () => store.get(caseId) ?? EMPTY,
  );
const busy = new Set<string>();

/** Asks the other screens to act, through the paths they already have. */
const highlightInGraph = (caseId: string, ids: string[]) =>
  window.dispatchEvent(
    new CustomEvent("suhail:graph-highlight", { detail: { caseId, ids } }),
  );
const openAuthorize = (caseId: string) =>
  window.dispatchEvent(
    new CustomEvent("suhail:authorize", { detail: { caseId } }),
  );

const clock = (value: string | null | undefined) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString("en-GB", {
        timeZone: "Asia/Riyadh",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

function Offer({ c, offer }: { c: OperationalCase; offer: CanopusOffer }) {
  const { service } = useOperations();
  const { t, preferences } = usePreferences();
  const [state, setState] = useState<"idle" | "confirm" | "sending" | "done">(
    "idle",
  );
  const [error, setError] = useState("");
  const label = (preferences.language === "ar" && offer.labelAr) || offer.label;
  if (!offer.allowed)
    return (
      <li className="ask-offer refused">
        <ShieldCheck size={12} />
        <span>
          <b>{label}</b>
          {t("Not available", "غير متاح")}: {offer.reason}
          {offer.ruleId && <i dir="ltr"> {offer.ruleId}</i>}
        </span>
      </li>
    );
  // A decision that has a dialog today is confirmed in that dialog, never from here.
  const viaDialog = offer.type !== "reanalyze";
  return (
    <li className="ask-offer">
      <ShieldCheck size={12} />
      <span>
        <b>{label}</b>
        {offer.reason}
        {error && <em role="alert">{error}</em>}
      </span>
      {viaDialog ? (
        <Button size="sm" variant="outline" onClick={() => openAuthorize(c.id)}>
          {t("Open Review & authorize", "فتح المراجعة والتفويض")}
        </Button>
      ) : state === "done" ? (
        <i>{t("Requested", "تم الطلب")}</i>
      ) : (
        <Button
          size="sm"
          variant={state === "confirm" ? "default" : "outline"}
          disabled={state === "sending" || !service.confirmCanopusOffer}
          onClick={() => {
            if (state === "idle") return setState("confirm");
            setState("sending");
            service.confirmCanopusOffer!(c.id, offer)
              .then(() => setState("done"))
              .catch((e: Error) => {
                setError(e.message);
                setState("idle");
              });
          }}
        >
          {state === "confirm"
            ? t("Confirm: send this request", "تأكيد: إرسال هذا الطلب")
            : t("Request it", "اطلبه")}
        </Button>
      )}
    </li>
  );
}

/**
 * The conversation about the open case. Canopus's answer, the agents' own recorded messages
 * and what the rules allow are three different things and are drawn as three: the answer is
 * labelled as Canopus's (or as built from the records when no model text was used), quotes are
 * source material with role and time, and an offer only opens the existing confirmation path.
 */
export function CanopusAskThread({ c }: { c: OperationalCase }) {
  const { t, preferences } = usePreferences();
  const turns = useTurns(c.id);
  if (!turns.length) return null;
  const arabic = preferences.language === "ar";
  return (
    <section className="ask-thread" data-testid="canopus-ask-thread">
      {turns.map((turn) => (
        <div key={turn.id} className="ask-turn">
          <p className="ask-question">{turn.question}</p>
          {!turn.answer && !turn.error && (
            <p className="ask-waiting" role="status">
              <Spinner className="size-3" />
              {t(
                "Canopus is reading this case's records…",
                "كانوبس يقرأ سجلات هذه الحالة…",
              )}
            </p>
          )}
          {turn.error && (
            <p className="ask-error" role="alert">
              {turn.error}
            </p>
          )}
          {turn.answer && (
            <>
              <article
                className={`narration-bubble ${turn.answer.kind === "canopus_answer" ? "narration-canopus_summary" : "narration-system_event"}`}
                data-testid="canopus-answer"
                data-kind={turn.answer.kind}
              >
                <header>
                  <span className="narration-kind">
                    {turn.answer.kind === "canopus_answer" ? (
                      <Sparkles size={11} />
                    ) : (
                      <Cpu size={11} />
                    )}
                    {turn.answer.kind === "canopus_answer"
                      ? t("Canopus answer", "إجابة كانوبس")
                      : t(
                          "Answer from the records · no model text",
                          "إجابة من السجلات · بلا نص من النموذج",
                        )}
                    {turn.answer.model && (
                      <i dir="ltr"> · {turn.answer.model}</i>
                    )}
                  </span>
                  <time>{clock(turn.answer.answeredAt)}</time>
                </header>
                <p dir={arabic && turn.answer.textAr ? "rtl" : "ltr"}>
                  {(arabic && turn.answer.textAr) || turn.answer.text}
                </p>
                <footer>
                  <span className="narration-state">
                    {t("Case state", "حالة الحالة")}:{" "}
                    {turn.answer.workflowState
                      .replaceAll("_", " ")
                      .toLowerCase()}
                  </span>
                  {turn.answer.evidenceIds.length > 0 && (
                    <button
                      type="button"
                      disabled={!turn.answer.graphNodeIds.length}
                      title={turn.answer.evidenceIds.join(", ")}
                      onClick={() =>
                        highlightInGraph(c.id, turn.answer!.graphNodeIds)
                      }
                    >
                      <Network size={11} />
                      {turn.answer.graphNodeIds.length
                        ? t(
                            `Show ${turn.answer.graphNodeIds.length} records in the graph`,
                            `إظهار ${turn.answer.graphNodeIds.length} سجلاً في الرسم`,
                          )
                        : t(
                            `${turn.answer.evidenceIds.length} references`,
                            `${turn.answer.evidenceIds.length} مرجعاً`,
                          )}
                    </button>
                  )}
                </footer>
              </article>
              {turn.answer.quotes.map((quote) => (
                <article
                  key={quote.recordId}
                  className="narration-bubble narration-agent_output"
                  data-testid="canopus-quote"
                >
                  <header>
                    <span className="narration-kind">
                      <Quote size={11} />
                      {quote.role === "reviewer"
                        ? t("Reviewer's own words", "كلام المراجع نفسه")
                        : t("Investigator's own words", "كلام المحقق نفسه")}
                      <i>
                        {" "}
                        ·{" "}
                        {t(
                          "recorded message, not rewritten",
                          "رسالة مسجلة، لم تُعد صياغتها",
                        )}
                      </i>
                    </span>
                    <time>{clock(quote.occurredAt)}</time>
                  </header>
                  {quote.title && <b>{quote.title}</b>}
                  <p dir="ltr">{quote.text}</p>
                  <footer>
                    <span dir="ltr">{quote.recordId}</span>
                  </footer>
                </article>
              ))}
              {turn.answer.offers.length > 0 && (
                <ul className="ask-offers" data-testid="canopus-offers">
                  {turn.answer.offers.map((offer, index) => (
                    <Offer key={`${offer.type}-${index}`} c={c} offer={offer} />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      ))}
    </section>
  );
}

const SUGGESTED: [string, string][] = [
  ["What did the reviewer say?", "ماذا قال المراجع؟"],
  ["What evidence is missing?", "ما الأدلة الناقصة؟"],
  [
    "Why is the case in this state, and what happens next?",
    "لماذا الحالة في هذا الوضع وما الخطوة التالية؟",
  ],
  [
    "Show me the investigator's original message.",
    "اعرض رسالة المحقق الأصلية.",
  ],
];

export function CanopusAskComposer({ c }: { c: OperationalCase }) {
  const { service } = useOperations();
  const { t, preferences } = usePreferences();
  const turns = useTurns(c.id);
  const [draft, setDraft] = useState("");
  const [, refresh] = useState(0);
  const waiting = busy.has(c.id);
  const ask = (question: string) => {
    const text = question.trim().slice(0, 500);
    if (!text || waiting || !service.askCanopus) return;
    const turn: Turn = { id: `${Date.now()}`, question: text };
    const earlier = store.get(c.id) ?? [];
    store.set(c.id, [...earlier, turn]);
    busy.add(c.id);
    setDraft("");
    emit();
    const history = earlier
      .filter((item) => item.answer)
      .slice(-3)
      .flatMap((item) => [
        { role: "operator" as const, text: item.question },
        { role: "canopus" as const, text: item.answer!.text },
      ]);
    service
      .askCanopus(c.id, text, preferences.language, history)
      .then((answer) => ({ answer }))
      .catch((e: Error) => ({ error: e.message }))
      .then((result) => {
        store.set(
          c.id,
          (store.get(c.id) ?? []).map((item) =>
            item.id === turn.id ? { ...item, ...result } : item,
          ),
        );
        busy.delete(c.id);
        emit();
        refresh((value) => value + 1);
      });
  };
  return (
    <div className="ask-composer" data-testid="canopus-ask">
      {turns.length === 0 && (
        <div className="ask-suggested">
          {SUGGESTED.map(([en, ar]) => (
            <button
              key={en}
              type="button"
              disabled={waiting}
              onClick={() => ask(t(en, ar))}
            >
              {t(en, ar)}
            </button>
          ))}
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
            "Ask Canopus about this case",
            "اسأل كانوبس عن هذه الحالة",
          )}
          placeholder={t(
            `Ask about ${c.shipment.id}…`,
            `اسأل عن ${c.shipment.id}…`,
          )}
          maxLength={500}
          value={draft}
          disabled={waiting}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          type="submit"
          size="icon"
          disabled={waiting || !draft.trim()}
          aria-label={t("Send question", "إرسال السؤال")}
        >
          {waiting ? <Spinner className="size-3" /> : <ArrowUp size={14} />}
        </Button>
      </form>
      <p className="chat-readonly">
        {t(
          "Canopus reads this case's records and performs no action. Agents' messages are quoted, not rewritten.",
          "يقرأ كانوبس سجلات هذه الحالة ولا ينفذ أي إجراء. رسائل الوكلاء تُقتبس ولا تُعاد صياغتها.",
        )}
      </p>
    </div>
  );
}
