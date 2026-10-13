import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  ShieldCheck,
  LoaderCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { CaseStatus, OperationalCase, Priority } from "@/domain/types";
import { statusLabels } from "@/domain/types";
import { workflowLabels } from "@/domain/case-view";
import { usePreferences } from "@/state/preferences";
import { Badge } from "@/components/ui/badge";
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { timeLabel } from "@/lib/dates";

const arabicStatus: Record<CaseStatus, string> = {
  queued: "في الانتظار",
  investigating: "قيد التحقيق",
  human_review: "بانتظار الموافقة",
  needs_evidence: "يتطلب أدلة",
  executing: "قيد التنفيذ",
  verifying: "التحقق من النتيجة",
  escalated: "تم التصعيد",
  resolved: "تم الحل",
};
export function StatusBadge({
  status,
  c,
}: {
  status: CaseStatus;
  /** A backend case shows its exact workflow state, not the lab's coarser label. */
  c?: OperationalCase;
}) {
  const { t } = usePreferences();
  const workflow = c?.backend ? workflowLabels[c.backend.workflowState] : null;
  return (
    <Badge variant="outline" className={`status-badge status-${status}`}>
      {status === "resolved" ? (
        <Check size={11} />
      ) : ["investigating", "executing", "verifying"].includes(status) ? (
        <LoaderCircle className="slow-spin" size={11} />
      ) : (
        <span className="status-dot" />
      )}
      {workflow
        ? t(workflow[0], workflow[1])
        : t(statusLabels[status], arabicStatus[status])}
    </Badge>
  );
}
export function PriorityLabel({ priority }: { priority: Priority }) {
  const { t } = usePreferences();
  return (
    <span className={`priority priority-${priority}`}>
      <i />
      {t(
        { high: "High", medium: "Medium", low: "Low", unknown: "Not set" }[
          priority
        ],
        { high: "مرتفع", medium: "متوسط", low: "منخفض", unknown: "غير محدد" }[
          priority
        ],
      )}
    </span>
  );
}
export function CaseLink({ id, label }: { id: string; label?: string }) {
  return (
    <Link className="case-link" to={`/cases/${id}`} title={label ? id : undefined}>
      {label || id}
      <ArrowUpRight size={12} />
    </Link>
  );
}
export function PageTitle({
  title,
  description,
  children,
  eyebrow,
}: {
  title: string;
  description: string;
  children?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="page-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="page-actions">{children}</div>
    </div>
  );
}
export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Empty className="empty-state">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ShieldCheck />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
export function SectionLink({
  to,
  children,
}: {
  to: string;
  children: React.ReactNode;
}) {
  return (
    <Link className="section-link" to={to}>
      {children}
      <ArrowRight size={13} />
    </Link>
  );
}
export function SmallTime({ timestamp }: { timestamp: string }) {
  return (
    <span className="small-time">
      <Clock3 size={11} />
      {timeLabel(timestamp)}
    </span>
  );
}
