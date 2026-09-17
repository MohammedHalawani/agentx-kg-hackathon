import { Progress as ProgressPrimitive } from "@base-ui/react/progress"
import { cn } from "cn"

export type OutcomeVariant = "default" | "success" | "failure" | "pending" | "neutral"

const outcomeIndicatorClass: Record<OutcomeVariant, string> = {
  default: "bg-primary",
  success: "bg-outcome-success",
  failure: "bg-outcome-failure",
  pending: "bg-outcome-pending",
  neutral: "bg-outcome-neutral",
}

function Progress({
  className,
  children,
  value,
  ...props
}: ProgressPrimitive.Root.Props) {
  return (
    <ProgressPrimitive.Root
      value={value}
      data-slot="progress"
      className={cn("flex flex-wrap gap-3", className)}
      {...props}
    >
      {children}
      <ProgressTrack>
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  )
}

function ProgressTrack({ className, ...props }: ProgressPrimitive.Track.Props) {
  return (
    <ProgressPrimitive.Track
      className={cn(
        "relative flex h-1 w-full items-center overflow-x-hidden rounded-full bg-progress-track",
        className
      )}
      data-slot="progress-track"
      {...props}
    />
  )
}

function ProgressIndicator({
  className,
  variant = "default",
  ...props
}: ProgressPrimitive.Indicator.Props & { variant?: OutcomeVariant }) {
  return (
    <ProgressPrimitive.Indicator
      data-slot="progress-indicator"
      className={cn("h-full transition-all", outcomeIndicatorClass[variant], className)}
      {...props}
    />
  )
}

export type OutcomeSegment = {
  value: number
  variant: OutcomeVariant
}

function SegmentedProgress({
  segments,
  className,
  trackClassName,
}: {
  segments: OutcomeSegment[]
  className?: string
  trackClassName?: string
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  const visible = segments.filter((segment) => segment.value > 0)

  if (total === 0) {
    return (
      <div
        data-slot="segmented-progress"
        className={cn(
          "flex h-1 w-full overflow-hidden rounded-full bg-progress-track",
          trackClassName,
          className,
        )}
        role="img"
        aria-label="No data"
      >
        <div className="h-full w-full bg-outcome-neutral/30" />
      </div>
    )
  }

  return (
    <div
      data-slot="segmented-progress"
      className={cn(
        "flex h-1 w-full overflow-hidden rounded-full bg-progress-track",
        trackClassName,
        className,
      )}
      role="img"
      aria-label={visible
        .map((segment) => `${segment.value} ${segment.variant}`)
        .join(", ")}
    >
      {visible.map((segment, index) => (
        <div
          key={`${segment.variant}-${index}`}
          data-slot="segmented-progress-segment"
          data-variant={segment.variant}
          className={cn(
            "h-full transition-all",
            outcomeIndicatorClass[segment.variant],
            index > 0 && "border-l border-progress-track/60",
          )}
          style={{ width: `${(segment.value / total) * 100}%` }}
        />
      ))}
    </div>
  )
}

function ProgressLabel({ className, ...props }: ProgressPrimitive.Label.Props) {
  return (
    <ProgressPrimitive.Label
      className={cn("text-sm font-medium", className)}
      data-slot="progress-label"
      {...props}
    />
  )
}

function ProgressValue({ className, ...props }: ProgressPrimitive.Value.Props) {
  return (
    <ProgressPrimitive.Value
      className={cn(
        "ml-auto text-sm text-muted-foreground tabular-nums",
        className
      )}
      data-slot="progress-value"
      {...props}
    />
  )
}

export {
  Progress,
  ProgressTrack,
  ProgressIndicator,
  SegmentedProgress,
  ProgressLabel,
  ProgressValue,
}
