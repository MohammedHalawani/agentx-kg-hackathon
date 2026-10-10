import { useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  CheckCheck,
  FlaskConical,
  ListChecks,
  ScanSearch,
  ShieldCheck,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCanopus } from "@/state/canopus";
import { usePreferences } from "@/state/preferences";
import type { CanopusReply } from "@/domain/canopus";

const blockInfo = {
  observation: {
    title: "Factual observation",
    ar: "ملاحظة فعلية",
    icon: ScanSearch,
  },
  hypothesis: {
    title: "Hypothesis · simulated",
    ar: "فرضية · محاكاة",
    icon: FlaskConical,
  },
  recommendation: {
    title: "Proposed action",
    ar: "إجراء مقترح",
    icon: ListChecks,
  },
  decision: {
    title: "Operator decision",
    ar: "قرار المشغل",
    icon: ShieldCheck,
  },
  outcome: { title: "Outcome", ar: "النتيجة", icon: CheckCheck },
};
export function CanopusReplyContent({ reply }: { reply: CanopusReply }) {
  const navigate = useNavigate(),
    { close } = useCanopus(),
    { t } = usePreferences();
  const references = [
    ...new Map(
      reply.blocks
        .flatMap((block) => block.references)
        .map((reference) => [`${reference.id}:${reference.href}`, reference]),
    ).values(),
  ];
  return (
    <div className="canopus-reply-blocks">
      {reply.blocks.map((block, i) => {
        const info = blockInfo[block.kind],
          Icon = info.icon;
        return (
          <details
            key={`${block.kind}-${i}`}
            className={`canopus-reply-block block-${block.kind} ${block.verified ? "verified" : ""}`}
          >
            <summary>
              <Icon size={12} />
              {block.kind === "outcome"
                ? block.verified
                  ? t("Verified outcome", "نتيجة متحققة")
                  : t("Outcome · unverified", "نتيجة · غير متحققة")
                : t(info.title, info.ar)}
              <ChevronDown size={12} className="canopus-detail-chevron" />
            </summary>
            <p dir="auto">{block.text}</p>
          </details>
        );
      })}
      {references.length > 0 && (
        <div
          className="canopus-citations"
          aria-label={t("Related references", "المراجع ذات الصلة")}
        >
          {references.map((reference) => (
            <Button
              key={`${reference.id}:${reference.href}`}
              asChild
              variant="outline"
              size="sm"
            >
              <a
                href={reference.href}
                data-reference-kind={reference.kind}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                  event.preventDefault();
                  navigate(reference.href);
                  close();
                }}
              >
                {reference.label}
                <ArrowUpRight size={10} />
              </a>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
