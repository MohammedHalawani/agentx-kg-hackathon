import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  CircleAlert,
  Search,
  ScanLine,
  Route,
  Forklift,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Users } from "@/components/animate-ui/icons/users";
import { Clock } from "@/components/animate-ui/icons/clock";
import { MessageSquareText } from "@/components/animate-ui/icons/message-square-text";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  SidebarGroup,
  SidebarGroupLabel,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { humanize } from "@/api/adapters";
import {
  assignmentIsRunning,
  investigationAssignments,
  workerCapacity,
} from "@/domain/desktop-operations";
import { stages, type InvestigationStatus } from "@/domain/types";

const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";
const PAGE_SIZE = 12;

function AssignmentTile({
  claim,
  online,
  selected,
  reduced,
  simulated,
}: {
  claim: InvestigationStatus;
  online: boolean;
  selected: boolean;
  reduced: boolean;
  simulated: boolean;
}) {
  const { t } = usePreferences();
  const { isMobile, setOpenMobile } = useSidebar();
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const playing = (hover || focus) && !reduced;
  const running = assignmentIsRunning(claim, online);
  const stage = claim.activeStage
    ? humanize(claim.activeStage)
    : t("Stage unavailable", "المرحلة غير متاحة");
  const state = !online
    ? t(
        "Last reported · connection interrupted",
        "آخر حالة مسجلة · الاتصال متقطع",
      )
    : running
      ? t("Investigating", "قيد التحقيق")
      : humanize(claim.runStatus);
  const identity = claim.workerId ?? t("Assigned investigator", "محقق مكلّف");
  const Icon = ["FAILED", "ERROR"].includes(claim.runStatus)
    ? CircleAlert
    : claim.runStatus === "PAUSED"
      ? Clock
      : claim.activeStage === "review"
        ? MessageSquareText
        : claim.activeStage === "retrieve"
          ? Search
          : claim.activeStage === "extract"
            ? ScanLine
            : claim.activeStage === "retrieve_context"
              ? Route
              : claim.activeStage === "custody_chain"
                ? Forklift
                : Users;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={`/cases/${encodeURIComponent(claim.caseId)}`}
          data-testid={`worker-case-${claim.caseId}`}
          className={`worker-tile ${selected ? "selected" : ""}`}
          data-running={running}
          aria-current={selected ? "page" : undefined}
          aria-label={`${identity} · ${claim.shipmentId || claim.caseId} · ${stage} · ${state}`}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          onClick={() => {
            if (isMobile) setOpenMobile(false);
          }}
        >
          <span className="worker-tile-icon">
            {Icon === Clock ? (
              <Clock animate={playing} />
            ) : Icon === MessageSquareText ? (
              <MessageSquareText animate={playing} />
            ) : Icon === Users ? (
              <Users animate={playing} />
            ) : (
              <Icon size={18} />
            )}
          </span>
          <span className="worker-tile-text">
            <b>{identity}</b>
            <small>{stage}</small>
          </span>
          <span
            className={`worker-activity ${running ? "running" : ""}`}
            aria-hidden="true"
          >
            <i />
            <i />
            <i />
          </span>
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right" className="worker-tooltip">
        <b>{identity}</b>
        <span dir="ltr">{claim.shipmentId || claim.caseId}</span>
        <span>
          {stage} · {state}
        </span>
        <small>
          {simulated
            ? t("Lab simulation", "محاكاة المختبر")
            : t(
                "Investigation assignment; provider calls remain gated.",
                "تكليف تحقيق؛ تظل استدعاءات المزوّد مقيدة بالبوابة.",
              )}
        </small>
      </TooltipContent>
    </Tooltip>
  );
}

export function WorkingAgents() {
  const {
    connection,
    cases,
    backend: fromBackend,
    automatic,
  } = useOperations();
  const { t, preferences } = usePreferences();
  const systemReduce = useReducedMotion();
  const reduced = preferences.motion === "reduce" || !!systemReduce;
  const { pathname } = useLocation();
  const selected = pathname.startsWith("/cases/")
    ? decodeURIComponent(pathname.split("/")[2] ?? "")
    : null;
  const backend = !LAB_BUILD || fromBackend;
  const worker = connection?.worker;
  const online = backend ? connection?.state === "online" : true;
  const assignments = backend
    ? investigationAssignments(worker, cases)
    : cases
        .filter((c) => c.status === "investigating")
        .map((c): InvestigationStatus => ({
          caseId: c.id,
          shipmentId: c.id,
          workerId: "Lab investigator",
          runId: c.run?.id ?? null,
          runStatus: "RUNNING",
          activeStage: stages[c.run?.stage ?? 0].label,
          workflowState: "INVESTIGATING",
          startedAt: c.run?.startedAt ?? null,
          updatedAt: null,
          leaseExpiresAt: null,
          asOf: null,
          stateVersion: 0,
        }));
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(assignments.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const free = backend
    ? workerCapacity(worker)
    : Math.max(0, 1 - assignments.length);
  const paused = backend ? worker?.state === "paused" : !automatic;
  const unavailable =
    !online ||
    (backend && (!worker || !["running", "paused"].includes(worker.state)));
  return (
    <SidebarGroup
      className="working-agents"
      data-testid="working-agents"
      data-reduced-motion={reduced}
      aria-label={t("Working agents", "وكلاء التحقيق")}
    >
      <SidebarGroupLabel>
        {t("WORKING AGENTS", "وكلاء التحقيق")}
      </SidebarGroupLabel>
      <p className="worker-roster-summary">
        <span>{t("Assigned", "مكلّف")}</span>
        <b>
          {backend ? (worker?.activeCount ?? "—") : assignments.length} /{" "}
          {backend ? (worker?.concurrency ?? "—") : 1}
        </b>
      </p>
      <div className="worker-grid">
        <AnimatePresence initial={false}>
          {assignments
            .slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
            .map((claim) => (
              <motion.div
                key={claim.workerId ?? claim.caseId}
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ duration: reduced ? 0 : 0.16 }}
              >
                <AssignmentTile
                  claim={claim}
                  online={online}
                  selected={selected === claim.caseId}
                  reduced={reduced}
                  simulated={!backend}
                />
              </motion.div>
            ))}
        </AnimatePresence>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className="worker-tile capacity-tile"
              tabIndex={0}
              data-testid="worker-capacity"
              aria-label={
                unavailable
                  ? t("Worker status unavailable", "حالة العمال غير متاحة")
                  : `${free} ${paused ? t("free capacity · auto paused", "سعة متاحة · التلقائي متوقف") : t("available capacity", "سعة متاحة")}`
              }
            >
              {unavailable ? (
                <CircleAlert size={18} />
              ) : paused ? (
                <Clock />
              ) : (
                <Users />
              )}
              <span className="worker-tile-text">
                <b>
                  {unavailable
                    ? t("Unavailable", "غير متاح")
                    : `${free} ${t("available", "متاح")}`}
                </b>
                <small>
                  {paused
                    ? t("Auto paused", "التلقائي متوقف")
                    : t("Pool capacity", "سعة المجموعة")}
                </small>
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">
            {unavailable
              ? t(
                  "Worker status is unavailable; assignments shown are the last reported snapshot.",
                  "حالة العمال غير متاحة؛ التكليفات المعروضة هي آخر لقطة مسجلة.",
                )
              : t(
                  `${free} unassigned investigation slots${paused ? "; automatic assignment is paused" : ""}.`,
                  `${free} أماكن تحقيق غير مكلّفة${paused ? "؛ التكليف التلقائي متوقف" : ""}.`,
                )}
          </TooltipContent>
        </Tooltip>
      </div>
      {pageCount > 1 && (
        <div className="worker-pages">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Previous worker page"
            disabled={!current}
            onClick={() => setPage(current - 1)}
          >
            <ChevronLeft size={12} />
          </Button>
          <small>
            {current + 1}/{pageCount}
          </small>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Next worker page"
            disabled={current === pageCount - 1}
            onClick={() => setPage(current + 1)}
          >
            <ChevronRight size={12} />
          </Button>
        </div>
      )}
    </SidebarGroup>
  );
}
