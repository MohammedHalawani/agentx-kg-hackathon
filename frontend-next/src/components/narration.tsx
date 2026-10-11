import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  Cpu,
  Network,
  Pause,
  Play,
  Quote,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { NarrationEvent, OperationalCase } from "@/domain/types";
import { stages } from "@/domain/types";
import { usePreferences } from "@/state/preferences";

/** The three sources a narration message can have; each is labelled, never blended. */
const KIND: Record<
  NarrationEvent["kind"],
  { en: string; ar: string; icon: typeof Sparkles }
> = {
  canopus_summary: { en: "Canopus summary", ar: "ملخص كانوبس", icon: Sparkles },
  agent_output: {
    en: "Agent's own words",
    ar: "كلام الوكيل نفسه",
    icon: Quote,
  },
  system_event: { en: "System record", ar: "سجل النظام", icon: Cpu },
};
const clock = (value: string | null) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString("en-GB", {
        timeZone: "Asia/Riyadh",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
/** An investigator's evidence query, narrated as it happened: many per round, shown compactly. */
const isCheck = (event: NarrationEvent) =>
  event.kind === "agent_output" && /^Investigator checks:/i.test(event.title);

export function NarrationBubble({
  event,
  active,
  onShow,
}: {
  event: NarrationEvent;
  active: boolean;
  onShow?: (event: NarrationEvent) => void;
}) {
  const { t, preferences } = usePreferences();
  const kind = KIND[event.kind];
  const Icon = kind.icon;
  const arabic = preferences.language === "ar";
  const title = (arabic && event.titleAr) || event.title;
  const text = (arabic && event.textAr) || event.text;
  return (
    <article
      className={`narration-bubble narration-${event.kind} ${active ? "active" : ""}`}
      data-testid="narration-bubble"
      data-kind={event.kind}
    >
      <header>
        <span className="narration-kind">
          <Icon size={11} />
          {t(kind.en, kind.ar)}
          {event.kind === "canopus_summary" && event.model && (
            <i dir="ltr"> · {event.model}</i>
          )}
          {event.fallback && (
            <i>
              {" "}
              ·{" "}
              {t(
                "record text, no model summary",
                "نص السجل، بلا ملخص من النموذج",
              )}
            </i>
          )}
        </span>
        <time title={event.occurredAt ?? undefined}>
          {clock(event.scenarioTime ?? event.occurredAt)}
        </time>
      </header>
      {title && <b>{title}</b>}
      <p dir={arabic && event.textAr ? "rtl" : "ltr"}>{text}</p>
      {(event.evidenceIds.length > 0 || event.outcomeState) && (
        <footer>
          {event.outcomeState && (
            <span className="narration-state">
              {t("Case state after this", "حالة الحالة بعد ذلك")}:{" "}
              {event.outcomeState.replaceAll("_", " ").toLowerCase()}
            </span>
          )}
          {event.evidenceIds.length > 0 && (
            <button
              type="button"
              disabled={!event.graphNodeIds.length || !onShow}
              onClick={() => onShow?.(event)}
              title={event.evidenceIds.join(", ")}
            >
              <Network size={11} />
              {event.graphNodeIds.length
                ? t(
                    `Show ${event.graphNodeIds.length} cited records in the graph`,
                    `إظهار ${event.graphNodeIds.length} سجلاً مستشهداً به في الرسم`,
                  )
                : t(
                    `${event.evidenceIds.length} references (not graph records)`,
                    `${event.evidenceIds.length} مرجعاً (ليست سجلات في الرسم)`,
                  )}
            </button>
          )}
        </footer>
      )}
    </article>
  );
}

/**
 * The backend's stored narration of a run, attached to the pipeline: what happened at the
 * selected step, in recorded order, each message labelled by who wrote it. Nothing is composed
 * here; an empty narration renders nothing. Replay steps through the stored messages again.
 */
export function NarrationStrip({
  c,
  stage,
  onStage,
  onHighlight,
  highlighted,
}: {
  c: OperationalCase;
  stage: number;
  onStage: (stage: number) => void;
  onHighlight: (ids: string[], eventId: string | null) => void;
  highlighted: string | null;
}) {
  const { t } = usePreferences();
  const events = useMemo(
    () => c.backend?.narration?.events ?? [],
    [c.backend?.narration],
  );
  const [open, setOpen] = useState(true);
  const [checksOpen, setChecksOpen] = useState(false);
  // Replay: how many stored messages are revealed (null = all, no replay running).
  const [replay, setReplay] = useState<number | null>(null);
  const live = c.status === "investigating";
  const last = events.at(-1);
  // While the run is live, follow the newest message: its step and its cited records.
  useEffect(() => {
    if (!live || !last) return;
    onStage(last.stage);
    if (last.graphNodeIds.length) onHighlight(last.graphNodeIds, last.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, last?.id]);
  useEffect(() => {
    if (replay === null) return;
    if (replay >= events.length) {
      setReplay(null);
      return;
    }
    const current = events[replay];
    onStage(current.stage);
    onHighlight(current.graphNodeIds, current.id);
    const timer = setTimeout(
      () => setReplay((value) => (value === null ? null : value + 1)),
      isCheck(current) ? 900 : 2600,
    );
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay, events]);
  if (!events.length) return null;
  const revealed = replay === null ? events : events.slice(0, replay + 1);
  const here = revealed.filter((event) => event.stage === stage);
  const checks = here.filter(isCheck);
  const messages = here.filter((event) => !isCheck(event));
  const status = c.backend?.narration?.status;
  return (
    <div className="narration-strip" data-testid="narration-strip">
      <div className="narration-head">
        <button
          type="button"
          className="narration-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <Sparkles size={13} />
          <b>{t("Canopus narration", "سرد كانوبس")}</b>
          <span>
            {stage === 6
              ? t("Disposition", "التصرف في الحالة")
              : t(stages[stage].label, stages[stage].arabic)}{" "}
            ·{" "}
            {t(
              `${here.length} of ${events.length} recorded messages`,
              `${here.length} من ${events.length} رسالة مسجلة`,
            )}
            {status === "narrating" && ` · ${t("live", "مباشر")}`}
            {replay !== null &&
              ` · ${t(`replaying ${Math.min(replay + 1, events.length)} of ${events.length}`, `إعادة ${Math.min(replay + 1, events.length)} من ${events.length}`)}`}
          </span>
          <ChevronDown size={13} className={open ? "open" : ""} />
        </button>
        {!live && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (replay !== null) {
                setReplay(null);
                onHighlight([], null);
              } else {
                setOpen(true);
                setReplay(0);
              }
            }}
            title={t(
              "Step through the stored messages of this run again, in their recorded order",
              "إعادة عرض الرسائل المخزنة لهذا التحقيق بترتيبها المسجل",
            )}
          >
            {replay !== null ? <Pause size={12} /> : <Play size={12} />}
            {replay !== null
              ? t("Stop replay", "إيقاف الإعادة")
              : t("Replay", "إعادة العرض")}
          </Button>
        )}
      </div>
      {open && (
        <div className="narration-body">
          {here.length === 0 && (
            <p className="narration-empty">
              {t(
                "No narration is recorded for this step.",
                "لا يوجد سرد مسجل لهذه الخطوة.",
              )}
            </p>
          )}
          {checks.length > 0 && (
            <div className="narration-checks" data-testid="narration-checks">
              <button
                type="button"
                aria-expanded={checksOpen}
                onClick={() => setChecksOpen((value) => !value)}
              >
                <Quote size={11} />
                {t(
                  `${checks.length} evidence checks by the investigator`,
                  `${checks.length} فحص أدلة أجراه المحقق`,
                )}
                <span>
                  {checks
                    .at(-1)!
                    .title.replace(/^Investigator checks:\s*/i, "")
                    .replaceAll("_", " ")}
                </span>
                <ChevronDown size={12} className={checksOpen ? "open" : ""} />
              </button>
              {(checksOpen || live || replay !== null) && (
                <ol>
                  {(checksOpen ? checks : checks.slice(-3)).map((event) => (
                    <li
                      key={event.id}
                      className={highlighted === event.id ? "active" : ""}
                    >
                      <button
                        type="button"
                        disabled={!event.graphNodeIds.length}
                        onClick={() =>
                          onHighlight(event.graphNodeIds, event.id)
                        }
                        title={t(
                          "The investigator's own stated purpose for this query. Click to show what it returned in the graph.",
                          "الغرض الذي ذكره المحقق لهذا الاستعلام. انقر لإظهار ما أعاده في الرسم.",
                        )}
                      >
                        <b>
                          {event.title
                            .replace(/^Investigator checks:\s*/i, "")
                            .replaceAll("_", " ")}
                        </b>
                        <span dir="ltr">{event.text}</span>
                        <i>
                          {event.graphNodeIds.length
                            ? `${event.graphNodeIds.length} ${t("records", "سجلات")}`
                            : ""}
                        </i>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <div className="narration-bubbles">
            {messages.map((event) => (
              <NarrationBubble
                key={event.id}
                event={event}
                active={highlighted === event.id}
                onShow={(item) => onHighlight(item.graphNodeIds, item.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** The same stored narration as a list for the Canopus panel, folded so questions stay in view. */
export function NarrationList({ c }: { c: OperationalCase }) {
  const { t } = usePreferences();
  const events = c.backend?.narration?.events ?? [];
  if (!events.length) return null;
  return (
    <details className="narration-list" data-testid="narration-list">
      <summary>
        <Sparkles size={12} />
        {t("Narration of this investigation", "سرد هذا التحقيق")}
        <span>
          {t(
            `${events.length} recorded messages`,
            `${events.length} رسالة مسجلة`,
          )}
        </span>
      </summary>
      {events
        .filter((event) => !isCheck(event))
        .map((event) => (
          <NarrationBubble key={event.id} event={event} active={false} />
        ))}
    </details>
  );
}
