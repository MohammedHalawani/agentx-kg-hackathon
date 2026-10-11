import type { OperationalCase } from "@/domain/types";

export type StageState =
  "queued" | "completed" | "waiting" | "running" | "failed";
export interface StageExplanation {
  /** One short sentence for the rail. */
  text: string;
  /** Always the case's own backend records; there are no fixed stage sentences. */
  source: "record";
}

const words = (code: string | null | undefined) =>
  (code ?? "").replaceAll("_", " ").toLowerCase();

/**
 * A short restatement of what the backend recorded for one pipeline step. It quotes recorded
 * fields only (stage events, the finding, the review, the authority decision, the execution and
 * the verified outcome); a step with nothing recorded yet, or not reached, shows nothing. The
 * narration of a run, when the backend serves it, is shown in its place.
 */
export function explainStage(
  c: OperationalCase,
  index: number,
  state: StageState,
): StageExplanation | null {
  const b = c.backend;
  if (!b || state === "queued") return null;
  const record = (text: string): StageExplanation => ({
    text,
    source: "record",
  });
  const recorded = b.stageDetail[index];
  const finding = b.investigation;
  const degraded = b.investigationLog?.degraded[0];
  if (index === 2) {
    if (state === "running")
      // The investigator's latest evidence query, as the backend reports it live.
      return recorded ? record(recorded) : null;
    if (degraded)
      return record(degraded.replace(/ A person has this case\.$/, ""));
    if (finding)
      return record(
        finding.accepted
          ? `Finding: ${words(finding.primaryCause)}${finding.confidence ? ` (the model states ${finding.confidence} confidence)` : ""}. Not verified.`
          : `Proposed ${words(finding.primaryCause)}; the reviewer did not accept it.`,
      );
  }
  if (index === 4 && state !== "running" && c.recommendation.available)
    return record(`Proposed: ${c.recommendation.title}`);
  if (index === 5 && state !== "running" && b.review?.verdict)
    return record(
      `${b.review.byModel ? "Independent reviewer" : "Deterministic evidence guard (no model review)"}: ${words(b.review.verdict)}${finding?.accepted && finding.confidence ? `; the model stated ${finding.confidence} confidence` : ""}.`,
    );
  if (index === 6 && state !== "running") {
    if (c.execution)
      return record(
        c.execution.successful
          ? `${b.authority?.riskClass === "AUTO" ? "Automatic action authorized by policy" : "Action approved by an operator"}; request delivered.`
          : "Action authorized, but the request could not be delivered.",
      );
    if (b.authority)
      return record(
        b.authority.riskClass === "AUTO"
          ? `Automatic action allowed by ${b.authority.ruleId}.`
          : `Held for a person by ${b.authority.ruleId}${b.allowed.approve ? "; the request can be approved" : ""}.`,
      );
  }
  if (index === 7) {
    const v = b.verification;
    if (v)
      return record(
        v.result === "confirmed"
          ? `Verifier confirmed the fix: ${v.reason}`
          : v.result === "exception_remains"
            ? `Action verified, but the exception remains: ${v.reason}`
            : v.result === "unanswered"
              ? "No confirming evidence arrived by the deadline. With a person."
              : v.result === "finding"
                ? `A person's finding is on record; not resolved: ${v.reason}`
                : `Verifier did not confirm the fix: ${v.reason}`,
      );
    if (c.status === "verifying")
      return record(
        "Request delivered. Waiting for evidence that it worked; the verifier decides.",
      );
    return null;
  }
  if (recorded && state !== "running") return record(recorded);
  return recorded ? record(recorded) : null;
}
