# V3.2 engineering handoff

Branch `codex/v3-2-case-intelligence`, worktree `C:\Projects\suhail-v3-2-case-intelligence`.
Exact base: `7287e44ad99c9a8b90aac7543e8218c1302aa31a`. Protected integration remains `765cb4033e6f0238d7cf758e20a89b54cfe6a0bf`. No merge, push, deployment, paid inference, real operational requests or Neo4j writes are part of this implementation.

## Implemented

Production inference now reserves calls, a conservative input/output token bound and cost before provider admission. The ignored durable ledger uses exclusive-file locking, fsync and atomic replacement. Concurrent clients cannot both spend the same allowance; crashes and unknown/failed usage keep their maximum charge. Confirmed bounded usage settles a reservation; abandoned requests retain their maximum. Over-limit provider usage is recorded and blocks further requests. No prompts, responses, keys or passwords enter this ledger.

One deadline covers budget admission, provider waiting and inference. The transport receives the remaining interval, capped by its existing HTTP timeout; caller timeout leaves the provider permit held until the underlying call ends. SDK retries remain disabled and explicit application attempts retain the canonical shared session counters. Output limits apply at client construction and each dispatch. Existing offline AFL/evaluator doubles forward the new transport arguments; evaluator-wrapper changes preserve output/timeout limits and inner retry suppression. No campaign was initiated.

The evidence-first public guide strengthens identity, custody, delayed receipt, shared-device, delivery-proof, route and weight investigations and independent source comparison. It contains no case IDs, preferred conclusions or evaluation answers. The complete user playbook is retained as 136 catalogue entries in 12 families. Twelve prioritized scenarios and five distinct coverage levels are in `coverage-matrix.md`; catalogue/source-kind availability is not presented as reliable model diagnosis.

OpsExecution now keeps independent authorization, dispatch, acknowledgement, acceptance, execution, verification and resolution facts through the additive `suhail-action-1` contract. Synthetic responses are explicit opt-in, local-authority protected, bounded, idempotent and source-bound. They cannot declare success or create evidence. Rejection, failed work and expiry are operationally unresolved; they do not automatically imply a policy decision. Genuine reviewer/authority floors retain human judgment. The old case states and frozen `suhail-v3-1` contract stay intact.

The existing verifier gains stricter source/package/facility/device/deadline checks for the new response protocol. Independent rescans must use a different evidenced device and match identity at a directed location. Synchronization requires the expected original custody observations and scan sources from the targeted device. Custody reconciliation requires newly corroborated, package-bound stock evidence at a directed facility. Vehicle GPS verifies none of these actions. Verification writes recheck the case version, response revision and clock to avoid committing a stale verdict after concurrent evidence changes. Authority, sensitive-action floors and exception-clearance policy are unchanged.

## Three workflows and actual outcomes

1. Barcode: authorized request → acknowledgement → acceptance/execution → new independent matching scan → actual source verifier → RESOLVED only after exception clearance. Continued mismatch, foreign source, stale scan, same-device read, missing provenance or contradiction cannot falsely close it.
2. Device: authorized synchronization → operational responses → original delayed records received from the exact target device → temporal/provenance and expected-observation verification → RESOLVED when remaining exceptions clear. Heartbeat, healthy-device acknowledgement or vehicle GPS alone cannot succeed.
3. Custody: directed reconciliation → acknowledgement/execution → independent scan and corroborated stock/custody observation → action VERIFIED. The controlled case retains an unconfirmed original handover, so it remains unresolved and follows existing escalation policy. The implementation never invents a historical transfer, loss, theft or blame to close it.

These execute the real store, authority rechecks, verifier and closure code on the existing transactional in-memory Neo4j port. Their initial accepted investigation is scripted to isolate request/response/verifier behavior. `offline-evaluation.json` includes actual rule IDs, source IDs and lifecycle histories. A serious recipient dispute also retains deterministic human authority; valid-looking proof does not erase nonreceipt.

The controlled evaluation currently reports 26 verifier probes (23 negative/ambiguous), zero false action successes, six complete store traces (four unresolved/safety boundaries), zero false case resolutions and two verified resolutions. Five scripted classification/citation probes, four substantive alternatives, one correct abstention and the independent wrong-interpretation rejection exercise the offline harness. **They are not live GPT-OSS accuracy measurements.** Full regression/frontend totals are finalized in `verification.json` after the gate.

## Configuration and reproduction

`.env.example` lists the new limits. Defaults: output 2048 tokens (hard configuration ceiling 8192), conservative input 65536 bytes plus framing, aggregate 100 calls / 1,000,000 tokens / USD 0.50 per ledger. Trusted input/output upper-bound tariffs in USD per million tokens must be supplied; absent, invalid or changed configuration fails closed before dispatch. These rates are operator assumptions, not provider prices looked up by this implementation. Validate them against the provider agreement before any separately authorized billable use. Account-wide caps also require every participating process to share the same ledger path; other applications are outside this guard.

The default ignored path is `.runtime/inference-budget.json`. Restart does not reset it. A policy change, corrupt ledger or abandoned lock refuses work; operator reconciliation is required. Do not delete reservations, remove a live lock, silently rotate the budget or release an abandoned permit to make a retry pass. Spend caps are conservative; a provider violating output limits/tariffs cannot be retroactively prevented from charging, but detected over-limit usage blocks further dispatch.

Run `scripts/v32_offline_evaluation.py` with the existing locked Python environment. It sets offline database/model endpoints and placeholder credentials, never imports expected answers into runtime code, and exports its results. Full unittest discovery must run from `chat` with both `chat` and `chat/tests` on PYTHONPATH and without `-t .`; explicitly disable `SUHAIL_NEO4J_TESTS` and `SUHAIL_V3_RACE_TESTS`. Use a temporary ledger and explicit test-only pricing/caps for the loopback tests. The complete run configuration and raw logs are retained in ignored `artifacts/v3.2`.

## Integration gates and next actions

- Await Claude Opus's independent V3.1 integration review. If it identifies a blocker, stop at a safe V3.2 commit and reconcile the base; this branch must not be merged over an unresolved V3.1 blocker.
- Independently review V3.2 budget durability, price assumptions, deadline handling, response idempotency/source checks, stale-verdict fences and human/closure boundaries. This offline branch is a review candidate, not a new live-production certification.
- Composer implements the additive consumer and pending/unresolved/verified/human distinctions from `composer-handoff.md`. Current browser checks validate compatibility of the unchanged frontend, not an implemented V3.2 interface.
- Before live database integration, separately provision/validate an isolated V3.2 mutable world target and synthetic response feed. Do not run this build on the protected integration, V2 databases or frozen V3 dataset. No new database/import/race gate is claimed here; disabled live tests remain skips.
- Live investigator/reviewer quality remains unmeasured. The other eight priority scenarios have bounded tools/policy support documented, not newly completed resolution vertical slices. Shared-incident request deduplication, real field authentication/integration, broad dataset generation, new provider/BGE-M3 work and paid evaluation remain outside this batch.

Rollback: disable the synthetic response feature, drain claims/provider requests, then revert the V3.2 commits only in the development/review branch. Preserve budget reservations and the frozen baseline. No data rollback is needed because this task wrote no Neo4j data.
