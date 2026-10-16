import { useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import { SelectControl } from "@/components/select-control";
import { usePreferences } from "@/state/preferences";
import { useOperations } from "@/state/operations";

import {
  defaultQueueFilters,
  type QueueFilters,
} from "@/domain/desktop-operations";

export function OperationsFilters({
  value,
  onChange,
  cities,
}: {
  value: QueueFilters;
  onChange: (filters: QueueFilters) => void;
  cities: string[];
}) {
  const { t, preferences } = usePreferences();
  const { catalog } = useOperations();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const fields = [
    {
      key: "collection",
      label: t("Case collection", "مجموعة الحالات"),
      aria: "Case collection",
      options: [
        {
          value: "unassigned",
          label: t("Unassigned candidates", "حالات غير مكلّفة"),
        },
        { value: "all", label: t("All loaded cases", "كل الحالات المحملة") },
        {
          value: "assigned",
          label: t("Assigned investigations", "تحقيقات مكلّفة"),
        },
        { value: "waiting", label: t("Waiting", "المنتظرة") },
        { value: "closed", label: t("Closed", "المغلقة") },
      ],
    },
    {
      key: "status",
      label: t("Workflow", "سير العمل"),
      aria: "Filter by status",
      options: [
        { value: "all", label: t("All workflows", "كل الحالات") },
        { value: "queued", label: t("Queued", "في الانتظار") },
        { value: "investigating", label: t("Investigating", "قيد التحقيق") },
        { value: "attention", label: t("Human attention", "تدخل بشري") },
        {
          value: "human_review",
          label: t("Awaiting approval", "بانتظار الموافقة"),
        },
        { value: "needs_evidence", label: t("Needs evidence", "يتطلب أدلة") },
        { value: "verifying", label: t("Verifying", "التحقق") },
        { value: "escalated", label: t("Escalated", "تم التصعيد") },
        { value: "resolved", label: t("Closed / resolved", "مغلقة / محلولة") },
      ],
    },
    {
      key: "priority",
      label: t("Priority", "الأولوية"),
      aria: "Filter by priority",
      options: [
        { value: "all", label: t("All priorities", "كل الأولويات") },
        { value: "high", label: t("High", "مرتفع") },
        { value: "medium", label: t("Medium", "متوسط") },
        { value: "low", label: t("Low", "منخفض") },
      ],
    },
    {
      key: "city",
      label: t("City", "المدينة"),
      aria: "Filter by city",
      options: [
        { value: "all", label: t("All cities", "كل المدن") },
        ...cities.map((city) => ({ value: city, label: city })),
      ],
    },
    {
      key: "cause",
      label: t("Exception cause", "سبب الاستثناء"),
      aria: "Filter by cause",
      options: [
        { value: "all", label: t("All causes", "كل الأسباب") },
        ...catalog.causes,
      ],
    },
    {
      key: "operational",
      label: t("Operational status", "الحالة التشغيلية"),
      aria: "Operational status filter",
      options: [
        { value: "all", label: t("All statuses", "كل الحالات") },
        ...catalog.operational.map((item) => ({
          value: item.value,
          label: t(item.label, item.arabic),
        })),
      ],
    },
    {
      key: "sort",
      label: t("Sort", "الترتيب"),
      aria: "Sort cases",
      options: [
        { value: "newest", label: t("Newest first", "الأحدث أولاً") },
        { value: "oldest", label: t("Oldest first", "الأقدم أولاً") },
        { value: "priority", label: t("Priority first", "الأولوية أولاً") },
      ],
    },
  ] as const;
  const applied = fields.filter(
    (field) => value[field.key] !== defaultQueueFilters[field.key],
  );
  return (
    <>
      <Sheet
        open={open}
        onOpenChange={(next) => {
          if (next) setDraft(value);
          setOpen(next);
        }}
      >
        <SheetTrigger asChild>
          <Button variant="outline" size="sm">
            <SlidersHorizontal size={14} />
            {t("Filters", "تصفية")}
            {applied.length > 0 && (
              <span className="filter-count">{applied.length}</span>
            )}
          </Button>
        </SheetTrigger>
        <SheetContent
          side={preferences.language === "ar" ? "left" : "right"}
          className="queue-filter-sheet"
        >
          <SheetHeader>
            <SheetTitle>{t("Queue filters", "تصفية القائمة")}</SheetTitle>
            <SheetDescription>
              {t(
                "Filter the loaded cases. Search includes all collections; claims are checked by the backend.",
                "تصفية الحالات المحملة. يشمل البحث كل المجموعات؛ يتحقق الخادم من التكليف.",
              )}
            </SheetDescription>
          </SheetHeader>
          <div className="queue-filter-fields">
            {fields.map((field) => (
              <div key={field.key}>
                <label>{field.label}</label>
                <SelectControl
                  label={field.aria}
                  value={draft[field.key]}
                  options={[...field.options]}
                  onChange={(next) =>
                    setDraft((previous) => ({ ...previous, [field.key]: next }))
                  }
                />
              </div>
            ))}
          </div>
          <SheetFooter>
            <Button
              onClick={() => {
                onChange(draft);
                setOpen(false);
              }}
            >
              {t("Apply filters", "تطبيق التصفية")}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setDraft(defaultQueueFilters);
                onChange(defaultQueueFilters);
              }}
            >
              {t("Clear filters", "مسح التصفية")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
      {applied.length > 0 && (
        <div
          className="queue-filter-chips"
          aria-label={t("Applied filters", "التصفية المطبقة")}
        >
          {applied.map((field) => (
            <Button
              key={field.key}
              size="sm"
              variant="secondary"
              aria-label={`Remove ${field.aria}`}
              onClick={() =>
                onChange({
                  ...value,
                  [field.key]: defaultQueueFilters[field.key],
                })
              }
            >
              {field.label}:{" "}
              {
                field.options.find(
                  (option) => option.value === value[field.key],
                )?.label
              }
              <X size={11} />
            </Button>
          ))}
        </div>
      )}
    </>
  );
}
