"""Public investigation procedure, derived from the user's logistics playbook.

No case identifiers, expected diagnoses, evaluation answers or private world state.
"""
EVIDENCE_GUIDE = """
CASE INTELLIGENCE PROCEDURE
Keep these separate in your findings: observed symptom; source records and their two clocks;
competing explanations; supported conclusion/uncertainty; authorized next evidence request;
the new evidence that would verify its effect. Routine employee work is not a human policy decision.

Identity: compare the manifest identity with raw reads, confidence, device and scan location.
An optical misread, wrong label, wrong physical parcel and duplicate identity need different
evidence. A prompt low-quality mismatch does not establish which one occurred. An independent
high-quality rescan can distinguish them; repeated mismatch needs identity verification.
Custody: trace actual acknowledged transfers and both endpoints. Assignment, manifest membership
and a vehicle's location do not establish possession. Distinguish a missing observation, an
unconfirmed transfer and contradictory possession claims. Direct checks to evidenced holders
or expected receiving facilities; never invent a handover, loss, theft or blame.
Device: compare occurrence and receipt times, device identity, connection evidence and which
specific package observations are absent. A heartbeat is not proof of uploaded custody. Similar
gaps on a shared device are incident context; verify each shipment separately after upload.
Delivery/status: bind proof, authentication, recipient and package; consider failed authentication,
proof for another shipment and a stale status projection. Vehicle GPS proves neither handover
nor delivery. A recipient dispute remains a policy question even if some proof appears valid.
Warehouse/route/weight: separate planned routing from observed receiving, reported vehicle
movement from parcel movement, and declared weight from an independent calibrated measurement.

For each material alternative, identify the source observation/tool result that could distinguish
it, record what it supports or contradicts and what remains unknown. Missing data cannot refute
an explanation. Keep confidence proportional to the evidence. Do not turn operational acceptance,
an acknowledgement, an old scan arriving late or an unrelated event into verified resolution.
"""

REVIEW_GUIDE = """
Independently compare the actual source fields with the claimed alternative test. An alternative
label or alternatives_tested=yes alone is not a substantive comparison. Explain which observations
discriminate and which uncertainty remains. Distinguish an evidence-gathering task from a policy
decision. Request revision or evidence when that can resolve uncertainty; reserve human judgment
for sensitive/disputed decisions or policy floors. You never authorize or verify an action outcome.
"""
