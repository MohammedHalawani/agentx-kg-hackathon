import type { OperationalCase } from "@/domain/types";

/** The last observation the backend served as confirmed custody (never a GPS position). */
export function lastConfirmedCustody(c: OperationalCase) {
  return (
    c.evidence
      .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
      .at(-1) ?? null
  );
}

const DELIVERY_SYMPTOMS = new Set([
  "DELIVERY_PROOF_INCOMPLETE",
  "DELIVERY_ATTEMPT_FAILED",
  "RECIPIENT_REPORTED_NOT_RECEIVED",
]);

/**
 * Proof-of-delivery records of the case's own evidence graph. `relevant` when the case is a
 * delivery or proof problem; `photos` are the PhotoEvidence records, each with the image the
 * backend serves for it, if any (an illustration, never evidence).
 */
export function proofOfDelivery(c: OperationalCase) {
  const b = c.backend;
  const relevant =
    !!b &&
    (b.operationalStatus === "DELIVERY_DISPUTE" ||
      b.symptomCodes.some((s) => DELIVERY_SYMPTOMS.has(s)));
  const photos = c.nodes
    .filter((node) => node.sourceKind === "PhotoEvidence")
    .map((node) => ({
      id: node.id,
      label: node.label,
      detail: node.detail,
      media: node.media,
    }));
  return { relevant, photos };
}

/**
 * A reviewed disposition or a handoff to a person is on record: the backend composed a brief
 * and the case is neither queued for nor in an investigation. Only then is a work order shown.
 */
export function isReviewedDisposition(c: OperationalCase) {
  const b = c.backend;
  if (!b?.brief || !b.detailLoaded) return false;
  if (
    ["OPEN", "REOPENED", "INVESTIGATING", "RECOMMENDATION_READY"].includes(
      b.workflowState,
    )
  )
    return false;
  return !["queued_for_investigation", "investigating"].includes(
    b.brief.waiting_kind ?? "",
  );
}
