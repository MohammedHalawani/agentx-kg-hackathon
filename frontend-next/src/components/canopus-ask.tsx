import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowUp, ChevronDown, Network } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CanopusAnswer, CanopusOffer, OperationalCase } from "@/domain/types";
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
/** How many questions the open case's conversation holds (for the panel's welcome text). */
// eslint-disable-next-line react-refresh/only-export-components
export const useAskCount = (caseId: string | undefined) =>
  useSyncExternalStore(
    subscribe,
    () => (caseId ? (store.get(caseId)?.length ?? 0) : 0),
    () => 0,
  );

/** Asks the other screens to act, through the paths they already have. */
const highlightInGraph = (caseId: string, ids: string[]) =>
  window.dispatchEvent(
    new CustomEvent("suhail:graph-highlight", { detail: { caseId, ids } }),
  );
const openAuthorize = (caseId: string) =>
  window.dispatchEvent(new CustomEvent("suhail:authorize", { detail: { caseId } }));

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
/** The operator asked to see an agent's own message, or why something cannot be done. */
const wantsQuote = (question: string) =>
  /original|exact|verbatim|quote|own words|actual (message|words)|what did .* (say|write)|show me .* message|الأصلي|حرفي|اقتبس|نص/i.test(
    question,
  );
const wantsWhyNot = (question: string) =>
  /why (can'?t|cannot|not|isn'?t)|can (you|i|we)|could (you|i)|request|approve|allowed|available|لماذا لا|هل يمكن|اطلب|وافق/i.test(
    question,
  );
/**
 * Internal state codes read as words in the conversation (AWAITING_OUTCOME -> "awaiting
 * outcome"). Presentation only: the sentence is the backend's, and the codes stay in details.
 */
const plain = (text: string) =>
  text.replace(/\b[A-Z][A-Z]+(?:_[A-Z]+)+\b/g, (code) =>
    code.replaceAll("_", " ").toLowerCase(),
  );

/** Paragraphs and short bullets, as a chat answer reads. */
function Prose({ text, rtl }: { text: string; rtl: boolean }) {
  const blocks: (string | string[])[] = [];
  for (const line of plain(text).split(/\n+/).map((item) => item.trim()).filter(Boolean)) {
    const bullet = /^(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
    const last = blocks.at(-1);
    if (bullet)
      if (Array.isArray(last)) last.push(bullet[1]);
      else blocks.push([bullet[1]]);
    else blocks.push(line);
  }
  return (
    <div className="chat-prose" dir={rtl ? "rtl" : "ltr"}>
      {blocks.map((block, index) =>
        Array.isArray(block) ? (
          <ul key={index}>
            {block.map((item, at) => (
              <li key={at}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{block}</p>
        ),
      )}
    </div>
  );
}

function OfferButton({ c, offer }: { c: OperationalCase; offer: CanopusOffer }) {
  const { service } = useOperations();
  const { t, preferences } = usePreferences();
  const [state, setState] = useState<"idle" | "confirm" | "sending" | "done">("idle");
  const [error, setError] = useState("");
  const label = (preferences.language === "ar" && offer.labelAr) || offer.label;
  // A decision that has a dialog today is confirmed in that dialog, never from here.
  if (offer.type !== "reanalyze")
    return (
      <Button size="sm" variant="outline" onClick={() => openAuthorize(c.id)}>
        {label} · {t("review and authorize", "راجع وفوّض")}
      </Button>
    );
  if (state === "done") return <span className="chat-note">{t("Requested.", "تم الطلب.")}</span>;
  return (
    <>
      <Button
        size="sm"
        variant={state === "confirm" ? "default" : "outline"}
        disabled={state === "sending" || !service.confirmCanopusOffer}
        onClick={() => {
          if (state === "idle") return setState("confirm");
          setState("sending");
          service
            .confirmCanopusOffer!(c.id, offer)
            .then(() => setState("done"))
            .catch((e: Error) => {
              setError(e.message);
              setState("idle");
            });
        }}
      >
        {state === "confirm" ? t(`Confirm: ${label}`, `تأكيد: ${label}`) : label}
      </Button>
      {error && (
        <span className="chat-note" role="alert">
          {error}
        </span>
      )}
    </>
  );
}

function Answer({ c, turn }: { c: OperationalCase; turn: Turn }) {
  const { t, preferences } = usePreferences();
  const [open, setOpen] = useState(false);
  const answer = turn.answer!;
  const arabic = preferences.language === "ar";
  const quoted = wantsQuote(turn.question);
  const sources = answer.evidenceIds.length || answer.graphNodeIds.length;
  const hasDetails =
    sources > 0 || (!quoted && answer.quotes.length > 0) || answer.unavailable.length > 0;
  const quotes = (
    <>
      {answer.quotes.map((quote) => (
        <blockquote key={quote.recordId} className="chat-quote" data-testid="canopus-quote">
          <small>
            {quote.role === "reviewer"
              ? t("The reviewer's own words", "كلام المراجع نفسه")
              : t("The investigator's own words", "كلام المحقق نفسه")}
            {quote.occurredAt && ` · ${clock(quote.occurredAt)}`}
          </small>
          <p dir="ltr">{quote.text}</p>
        </blockquote>
      ))}
    </>
  );
  return (
    <div className="chat-answer" data-testid="canopus-answer" data-kind={answer.kind}>
      <Prose
        text={(arabic && answer.textAr) || answer.text}
        rtl={arabic && !!answer.textAr}
      />
      {quoted && quotes}
      {answer.unavailable.length > 0 && wantsWhyNot(turn.question) && (
        <ul className="chat-why-not" data-testid="canopus-unavailable">
          {answer.unavailable.map((item, index) => (
            <li key={index}>{plain((arabic && item.reasonAr) || item.reason)}</li>
          ))}
        </ul>
      )}
      {answer.offers.length > 0 && (
        <div className="chat-offers" data-testid="canopus-offers">
          {answer.offers.map((offer, index) => (
            <OfferButton key={`${offer.type}-${index}`} c={c} offer={offer} />
          ))}
        </div>
      )}
      <div className="chat-meta">
        <span>
          Canopus
          {answer.kind === "record_answer" &&
            ` · ${t("from the case record", "من سجل الحالة")}`}
          {answer.answeredAt && ` · ${clock(answer.answeredAt)}`}
        </span>
        {answer.graphNodeIds.length > 0 && (
          <button type="button" onClick={() => highlightInGraph(c.id, answer.graphNodeIds)}>
            <Network size={11} />
            {t("Show in graph", "أظهر في الرسم")}
          </button>
        )}
        {hasDetails && (
          <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
            {t("Sources", "المصادر")}
            <ChevronDown size={11} className={open ? "open" : ""} />
          </button>
        )}
      </div>
      {open && (
        <div className="chat-sources" data-testid="canopus-sources">
          {!quoted && quotes}
          {answer.evidenceIds.length > 0 && (
            <p dir="ltr">
              {t("Records", "السجلات")}: {answer.evidenceIds.join(", ")}
            </p>
          )}
          {answer.model && (
            <p dir="ltr">
              {t("Written by", "كتبه")} {answer.model}{" "}
              {t("from this case's records", "من سجلات هذه الحالة")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The conversation about the open case, as a plain chat: the operator's messages on one side,
 * Canopus's answers on the other in readable paragraphs. An agent's own recorded message is
 * shown only when asked for, quoted and labelled; records and the model are under "Sources";
 * an action appears only when the rules allow it now, and only opens the existing confirmation.
 */
export function CanopusAskThread({ c }: { c: OperationalCase }) {
  const { t } = usePreferences();
  const turns = useTurns(c.id);
  const end = useRef<HTMLDivElement>(null);
  const last = turns.at(-1);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, last?.answer, last?.error]);
  if (!turns.length) return null;
  return (
    <section className="chat-thread" data-testid="canopus-ask-thread">
      {turns.map((turn) => (
        <div key={turn.id} className="chat-turn">
          <p className="chat-question">{turn.question}</p>
          {!turn.answer && !turn.error && (
            <p className="chat-typing ask-waiting" role="status">
              <i />
              <i />
              <i />
              <span>{t("Reading the case…", "يقرأ الحالة…")}</span>
            </p>
          )}
          {turn.error && (
            <p className="chat-error ask-error" role="alert">
              {turn.error}
            </p>
          )}
          {turn.answer && <Answer c={c} turn={turn} />}
        </div>
      ))}
      <div ref={end} />
    </section>
  );
}

const SUGGESTED: [string, string][] = [
  ["What happened to this shipment?", "ماذا حدث لهذه الشحنة؟"],
  ["What is Suhail waiting for?", "ماذا ينتظر سهيل؟"],
  ["Who needs to act next?", "من يجب أن يتصرف بعد ذلك؟"],
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
    <div className="chat-composer-area" data-testid="canopus-ask">
      {turns.length === 0 && (
        <div className="chat-suggested">
          {SUGGESTED.map(([en, ar]) => (
            <button key={en} type="button" disabled={waiting} onClick={() => ask(t(en, ar))}>
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
          aria-label={t("Ask Canopus about this case", "اسأل كانوبس عن هذه الحالة")}
          placeholder={t(`Ask about ${c.shipment.id}…`, `اسأل عن ${c.shipment.id}…`)}
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
          <ArrowUp size={14} />
        </Button>
      </form>
    </div>
  );
}
