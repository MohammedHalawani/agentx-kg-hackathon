import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";
import type {
  CanopusContext,
  CanopusRequest,
  CanopusScreen,
  CanopusService,
} from "@/domain/canopus";
import type { ChatEntry, ChatParticipant } from "@/domain/chat";
import { MockCanopusService } from "@/services/mock-canopus";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { CanopusPanel } from "@/components/canopus-panel";
import { parsePageIntent } from "@/services/mock-intents";
import type { AssistantContext, PageAction } from "@/domain/page-actions";

export type CanopusPresentation = "collapsed" | "floating" | "expanded";
export interface CanopusPageTools {
  pathname: string;
  context: () => AssistantContext;
  apply: (actions: PageAction[]) => string;
  undo: () => void;
}

type Thread = {
  messages: ChatEntry[];
  busy: boolean;
  activity?: string;
};
type RegistryContext = CanopusContext & { pathname: string };
const keyFor = (context: CanopusContext) =>
  context.caseId ?? `screen:${context.screen}`;
const emptyThread: Thread = { messages: [], busy: false };
const Context = createContext<{
  screenContext: CanopusContext;
  panelContext: CanopusContext;
  panelOpen: boolean;
  presentation: CanopusPresentation;
  setPresentation: (state: CanopusPresentation) => void;
  open: (context?: CanopusContext) => void;
  close: () => void;
  selectCase: (caseId?: string) => void;
  registerScreen: (context: RegistryContext) => void;
  registerPageTools: (tools: CanopusPageTools) => () => void;
  canUndo: boolean;
  undoFilters: () => void;
  thread: (context: CanopusContext) => Thread;
  send: (
    context: CanopusContext,
    message: string,
    participant?: ChatParticipant,
    simulateFailure?: boolean,
  ) => Promise<void>;
  retry: (context: CanopusContext, messageId: string) => Promise<void>;
  clear: () => void;
} | null>(null);

export function CanopusProvider({
  children,
  adapter,
}: {
  children: ReactNode;
  adapter?: CanopusService;
}) {
  const location = useLocation();
  const { service, cases } = useOperations();
  const { preferences } = usePreferences();
  const [canopus] = useState<CanopusService>(
    () => adapter ?? new MockCanopusService(service.getSnapshot),
  );
  const [registered, setRegistered] = useState<RegistryContext | null>(null);
  const [presentation, setPresentationState] =
    useState<CanopusPresentation>("collapsed");
  const lastMode = useRef<"floating" | "expanded">("floating");
  const presentationRef = useRef(presentation);
  presentationRef.current = presentation;
  const setPresentation = useCallback((state: CanopusPresentation) => {
    if (state !== "collapsed") lastMode.current = state;
    setPresentationState(state);
  }, []);
  const close = useCallback(() => setPresentationState("collapsed"), []);
  const [panelContext, setPanelContext] = useState<CanopusContext>({
    screen: "operations",
  });
  const [threads, setThreads] = useState<Record<string, Thread>>(() => {
    try {
      const saved = JSON.parse(
        sessionStorage.getItem("suhail-ui-lab.chat") ?? "{}",
      ) as Record<string, ChatEntry[]>;
      return Object.fromEntries(
        Object.entries(saved).map(([id, messages]) => [
          id,
          {
            messages: messages.map((m, i) => ({
              ...m,
              id: m.id ?? `${id}-${i}`,
              timestamp: m.timestamp ?? new Date().toISOString(),
              streaming: false,
              error: m.streaming
                ? preferences.language === "ar"
                  ? "توقفت إجابة المحاكاة قبل اكتمالها. أعد المحاولة للمتابعة."
                  : "The simulated response was interrupted. Retry to continue."
                : m.error,
            })),
            busy: false,
          },
        ]),
      );
    } catch {
      return {};
    }
  });
  const requests = useRef(new Map<string, AbortController>());
  const pageTools = useRef<CanopusPageTools | null>(null);
  const [lastPageAction, setLastPageAction] = useState<{
    pathname: string;
    context: CanopusContext;
  } | null>(null);
  const openedPath = useRef<string | null>(null);
  const threadsRef = useRef(threads);
  threadsRef.current = threads;
  useEffect(() => {
    const active = requests.current;
    return () => {
      active.forEach((controller) => controller.abort());
    };
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem(
        "suhail-ui-lab.chat",
        JSON.stringify(
          Object.fromEntries(
            Object.entries(threads).map(([id, thread]) => [
              id,
              thread.messages,
            ]),
          ),
        ),
      );
    } catch {
      /* Session storage is optional. */
    }
  }, [threads]);
  const routeScreen: CanopusScreen = location.pathname.startsWith("/cases/")
    ? "investigation"
    : ["operations", "decisions", "explore", "audit", "settings"].includes(
          location.pathname.slice(1),
        )
      ? (location.pathname.slice(1) as CanopusScreen)
      : "operations";
  const screenContext: CanopusContext =
    registered?.pathname === location.pathname
      ? registered
      : {
          screen: routeScreen,
          caseId:
            routeScreen === "investigation"
              ? location.pathname.split("/")[2]
              : undefined,
        };
  const registerScreen = useCallback((context: RegistryContext) => {
    setRegistered(context);
    if (
      presentationRef.current !== "collapsed" &&
      openedPath.current !== context.pathname
    ) {
      setPanelContext(context);
      openedPath.current = context.pathname;
    }
  }, []);
  const registerPageTools = useCallback((tools: CanopusPageTools) => {
    pageTools.current = tools;
    return () => {
      if (pageTools.current === tools) pageTools.current = null;
      setLastPageAction((last) =>
        last?.pathname === tools.pathname ? null : last,
      );
    };
  }, []);
  async function stream(request: CanopusRequest, assistantId: string) {
    const key = keyFor(request.context),
      controller = new AbortController();
    requests.current.set(key, controller);
    const update = (fn: (thread: Thread) => Thread) =>
      setThreads((all) => ({ ...all, [key]: fn(all[key] ?? emptyThread) }));
    update((thread) => ({
      ...thread,
      busy: true,
      messages: thread.messages.map((m) =>
        m.id === assistantId
          ? {
              ...m,
              text: "",
              reply: undefined,
              error: undefined,
              streaming: true,
              request,
            }
          : m,
      ),
    }));
    try {
      for await (const event of canopus.stream(request, {
        signal: controller.signal,
      })) {
        if (controller.signal.aborted) break;
        if (event.type === "activity")
          update((thread) => ({ ...thread, activity: event.text }));
        else if (event.type === "delta")
          update((thread) => ({
            ...thread,
            messages: thread.messages.map((m) =>
              m.id === assistantId ? { ...m, text: m.text + event.text } : m,
            ),
          }));
        else
          update((thread) => ({
            ...thread,
            messages: thread.messages.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    text: event.reply.summary,
                    reply: event.reply,
                    streaming: false,
                  }
                : m,
            ),
          }));
      }
    } catch (error) {
      if (!controller.signal.aborted)
        update((thread) => ({
          ...thread,
          messages: thread.messages.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  streaming: false,
                  error:
                    error instanceof Error
                      ? error.message
                      : "The simulated response failed.",
                }
              : m,
          ),
        }));
    } finally {
      if (requests.current.get(key) === controller)
        requests.current.delete(key);
      if (!controller.signal.aborted)
        update((thread) => ({ ...thread, busy: false, activity: undefined }));
    }
  }
  async function send(
    context: CanopusContext,
    message: string,
    participant: ChatParticipant = "suhail",
    simulateFailure = false,
  ) {
    if (!message.trim() || requests.current.has(keyFor(context))) return;
    const key = keyFor(context),
      now = new Date().toISOString(),
      assistantId = crypto.randomUUID();
    const request: CanopusRequest = {
      id: crypto.randomUUID(),
      message: message.trim(),
      context,
      participant,
      language: preferences.language,
      simulateFailure,
    };
    setThreads((all) => ({
      ...all,
      [key]: {
        ...(all[key] ?? emptyThread),
        messages: [
          ...(all[key]?.messages ?? []),
          {
            id: crypto.randomUUID(),
            role: "user",
            text: request.message,
            timestamp: now,
          },
          {
            id: assistantId,
            role: "assistant",
            text: "",
            timestamp: now,
            agent: participant,
            streaming: true,
            request,
          },
        ],
        busy: true,
      },
    }));
    // Page tools remain local UI rules. Explanatory questions use the replaceable service.
    const tools = pageTools.current;
    if (
      !simulateFailure &&
      tools?.pathname === location.pathname &&
      tools.context().page === context.screen &&
      /^(?:@suhail\s+)?(?:show|highlight|focus|zoom|switch|undo|اعرض|أبرز|ركز|ركّز|كبّر|تراجع)(?:\s|$)/i.test(
        message.trim(),
      )
    ) {
      const result = parsePageIntent(
        message,
        tools.context(),
        cases,
        preferences.language,
      );
      const text = result.supported
        ? tools.apply(result.actions)
        : result.explanation;
      if (result.supported)
        setLastPageAction({ pathname: tools.pathname, context });
      setThreads((all) => ({
        ...all,
        [key]: {
          ...all[key],
          busy: false,
          messages: all[key].messages.map((m) =>
            m.id === assistantId
              ? { ...m, text, streaming: false, actions: result.actions }
              : m,
          ),
        },
      }));
      return;
    }
    await stream(request, assistantId);
  }
  async function retry(context: CanopusContext, messageId: string) {
    const thread = threadsRef.current[keyFor(context)],
      message = thread?.messages.find((m) => m.id === messageId);
    if (
      message?.request &&
      message.error &&
      !thread?.busy &&
      !requests.current.has(keyFor(context))
    )
      await stream({ ...message.request, simulateFailure: false }, message.id);
  }
  const currentPanelContext =
    panelContext.caseId && panelContext.caseId === screenContext.caseId
      ? {
          ...panelContext,
          selectedEvidenceId: screenContext.selectedEvidenceId,
          stage: screenContext.stage,
          filters: screenContext.filters,
        }
      : panelContext;
  const value = {
    screenContext,
    panelContext: currentPanelContext,
    panelOpen: presentation !== "collapsed",
    presentation,
    setPresentation,
    open: (context?: CanopusContext) => {
      const newContext = context || openedPath.current !== location.pathname;
      if (newContext) setPanelContext(context ?? screenContext);
      openedPath.current = location.pathname;
      setPresentation(newContext ? "floating" : lastMode.current);
    },
    close,
    selectCase: (caseId?: string) =>
      setPanelContext((c) => ({ screen: c.screen, caseId })),
    registerScreen,
    registerPageTools,
    canUndo:
      lastPageAction?.pathname === location.pathname &&
      pageTools.current?.pathname === location.pathname,
    undoFilters: () => {
      const tools = pageTools.current;
      if (
        !lastPageAction ||
        !tools ||
        tools.pathname !== location.pathname ||
        lastPageAction.pathname !== tools.pathname
      )
        return;
      tools.undo();
      const key = keyFor(lastPageAction.context);
      setThreads((all) => ({
        ...all,
        [key]: {
          ...(all[key] ?? emptyThread),
          messages: [
            ...(all[key]?.messages ?? []),
            {
              id: crypto.randomUUID(),
              role: "assistant",
              agent: "suhail",
              text:
                preferences.language === "ar"
                  ? "استُعيدت التصفية والتحديد والعرض السابق."
                  : "Previous filters, selection, and view restored.",
              timestamp: new Date().toISOString(),
            },
          ],
        },
      }));
      setLastPageAction(null);
    },
    thread: (context: CanopusContext) =>
      threads[keyFor(context)] ?? emptyThread,
    send,
    retry,
    clear: () => {
      requests.current.forEach((controller) => controller.abort());
      requests.current.clear();
      setThreads({});
      setLastPageAction(null);
    },
  };
  return (
    <Context.Provider value={value}>
      {children}
      <CanopusPanel />
    </Context.Provider>
  );
}
export function useCanopus() {
  const value = useContext(Context);
  if (!value) throw new Error("CanopusProvider missing");
  return value;
}
/** Each page publishes its current selection without coupling the assistant to page internals. */
export function useCanopusScreen(context: CanopusContext) {
  const { pathname } = useLocation(),
    { registerScreen } = useCanopus();
  const key = JSON.stringify(context);
  const current = useMemo(() => JSON.parse(key) as CanopusContext, [key]);
  useEffect(() => {
    registerScreen({ ...current, pathname });
  }, [current, pathname, registerScreen]);
}
