import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useCanopus } from "@/state/canopus";
import type { AssistantContext, PageAction } from "@/domain/page-actions";

/** Registers the existing page controls with the single global Canopus window. */
export function PageAssistant({
  context,
  onApply,
  onUndo,
}: {
  context: AssistantContext;
  onApply: (actions: PageAction[]) => string;
  onUndo: () => void;
}) {
  const { pathname } = useLocation();
  const { registerPageTools } = useCanopus();
  const latest = useRef({ context, onApply, onUndo });
  latest.current = { context, onApply, onUndo };
  useEffect(
    () =>
      registerPageTools({
        pathname,
        context: () => latest.current.context,
        apply: (actions) => latest.current.onApply(actions),
        undo: () => latest.current.onUndo(),
      }),
    [pathname, registerPageTools],
  );
  return null;
}
