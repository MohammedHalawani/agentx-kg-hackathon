# Dataset V2 foundation independent review

Recorded 2026-10-08 19:25 UTC / 22:25 Asia/Riyadh. Reviewer: independent Codex agent; AI engineering review, not human/SPL operational adjudication.

Scope: read-only review of `chat/dataset_v2/contracts.py`, `generate.py`, `context.py`, `export.py` and `docs/dataset-v2/contracts.md`, against the latest 2000-shipment implementation request and the seven committed V2 design documents. Relevant derivation/validation contracts were traced where needed. No source edits, database/model/network calls, UI work, import or live notification occurred. This review note is the only artifact written by this reviewer.

## Initial findings — fixes required

1. **Future evidence in historical proposal/review.** `historical_outcomes` assigned follow-up recovery/load/delivery-proof/reconciliation IDs to Recommendation/Review records timestamped before those observations. Offline default-seed `generate(Config(total=300))` produced 108 such records while the then-current validator reported PASS. For example, `DEMO-SHP-000015-HISTORY-1-REC` occurred at 2026-09-16T15:01Z but cited recovery at 15:16Z and later delivery. Proposal/review must use initial investigation evidence; Resolution/Outcome may use completion evidence available at verification time. Validate occurrence and ingestion time against each citing stage.

2. **Future physical custody leaked through relationships.** Initial `evidence_context` removed future observation nodes but exported future `LOADED_ON` edges and expanded their shared Vehicle endpoints. The same probe found 54 affected shipment contexts. `DEMO-SHP-000015` at 2026-09-16T14:01Z exposed a follow-up load beginning 2026-09-17T03:00Z and its withheld custody-event ID. Apply observation/time/reference eligibility before catalog expansion and relationship export. A future observed custody endpoint cannot be treated as an already-known physical fact.

3. **Vehicle custody interval outlasted handoff.** Initial base last-mile `LOADED_ON.valid_to` used session end plus grace, rather than corroborated delivery/return evidence. The probe found 468 edges ending after a raw terminal observation; this count includes all terminal observations, so it is not a count of independently confirmed handoffs. Confirmed examples: SHP-000001 had a corroborated return at 13:15Z but association through 14:00Z; SHP-000002 delivered at 05:00Z but association through 14:00Z. Close from corroborated end evidence and preserve an explicit unknown/open observation gap when no such evidence exists. A planned deadline does not prove physical custody ended.

4. **Conflict diagnostic supplied in raw source metadata.** The conflicting-custody recipe inserted `source_quality=CONFLICTING_REPORT`, and derivation used this marker directly as conflict truth. Contradiction should remain derivable from incompatible raw holder/transfer observations after removing a diagnostic quality label; neutral report quality and provenance may remain. This concern was sent to the derivation owner/coordinator for assessment.

5. **Normal second-attempt contact wording.** The first failed contact in the normal second-attempt recipe said `AGREED_NEXT_SESSION`, although its second attempt occurred one hour later in the same session. Use a same-session agreed time-window result, or move the attempt consistently to the next session. This is a small scenario coherence defect.

## Positive contract coverage

- Configurable total/splits default to 2000/1200/400/400 and majority healthy journeys. The reviewed 300-shipment probe had 210 shipments without Case; healthy shipments were not assigned fabricated remediation histories.
- Seven provenance roles remain orthogonal to `synthetic=true`; generated approval/execution/verification are explicitly offline fixtures. DEMO identities, no real OTP/signature/photo, zero notification provider calls and neutral recipient reports are explicit.
- Package manifests, handling/capacity, versioned addresses/instructions/pins, contextual route/plan/milestones, separate overnight linehaul and local sessions, attempts/contact, custody source acknowledgments and vehicle-only GPS are represented.
- Delivery reports remain disputes despite corroborating proof; wrong-location, failed authentication, photo-only, alternate-recipient and partial-package variants provide distinct observations. Missing reconciliation is not labeled LOST and does not blame a person.
- Shipment-owned groups/splits propagate through objects and relationships; runtime type selection excludes Cases/Exceptions/remediation outcomes and scoring fields. Gold is separately exported and must remain excluded by the importer. Shared catalogs contain no recipe/cause annotations.
- Export validates before publishing, writes deterministic sorted canonical records/hashes, refuses an existing destination and stages an atomic bundle directory. It performs no database or provider activity.

## Gate status and limits

**Initial review: fixes required before PASS.** The coordinator has received reproducible examples and is applying narrow source/validator changes. Final status must be appended after reinspection and an offline probe of the repaired source; the initial findings above are retained as review history.

This review has not certified a 2000-shipment run, importer/database isolation, actual physical delivery, independent outcome authority, SPL infrastructure, production model quality or a V2 evaluation. It relies on synthetic source-backed observations and reference rules. Future evidence/RAG consumers must preserve as-of boundaries and whole-shipment holdout isolation.


## Resolution at the frozen main export

All five initial findings were repaired before the final 2000-shipment export: proposal/review cite initial evidence only; future relationship filtering precedes catalog expansion; vehicle custody ends only on corroborated end evidence; independently attributed incompatible custody reports establish conflict without a diagnostic raw label; same-session retry contact wording was corrected. Mutation and chronology tests plus 5,578,346 main validation checks passed. Main manifest hash: `3cbbbb565bbdc6bece988ed83826e99895c1e42e712625f7ba1809e0bbe9890c`. This section records root verification of the repairs; it does not relabel the initial independent review as a human operational decision.
