# Approved Suhail V3 bootstrap

Contract version: **suhail-v3-1**, approved and frozen on 13 October 2026. Composer Phase C is included in the signoff gates. No paid inference, API migration or broad evaluation is authorized.

Protected base: `fhd` commit `4cd43045a1db284e83cd5702d63acf7950492492` in `C:\Projects\demo`.

Recording frontend source: commit `5aab052daead6141bf54fda068f7bd4bdcba3cb2`, `frontend-next` subtree from `C:\Projects\demo\.ui-integration`. Only committed subtree content is imported; original videos and untracked files stay untouched. Backend/chat/scripts are unchanged from the protected base.

The final common bootstrap SHA is published in `C:\Projects\suhail-v3-plan-2026-10-13\12-bootstrap-readiness.md` after source checks and commit creation. All three downstream worktrees must begin at that exact SHA before code edits. The bootstrap chat stops at that checkpoint; the user distributes the Claude/Composer/separate Sol High tasks.

## Handoffs

- [Complete approved handoff](00-complete-handoff.md).
- [Master plan](01-master-plan.md).
- [Fable coordinator and Opus concurrency brief](02-fable-opus-prompt.md).
- [Separate Sol High dataset/GPS task](03-sol-dataset-prompt.md).
- [Composer Phase A](04-composer-phase-a-prompt.md).
- [Composer Phase B](05-composer-phase-b-prompt.md).
- [Composer Phase C independent evidence/storyline QA](09-composer-phase-c-prompt.md).
- [Final Sol integration](07-sol-integration-prompt.md).
- [Frozen wire examples](06-contract-examples.json) and [interface rules](08-interface-reference.md).
- [Approved ownership and milestone addition](11-approved-coordination-addendum.md).

Keep all development in the assigned V3 worktree. Synced project sources, main fhd, `.stage4`, `.ui-integration`, V2 databases, port 8022 and final video recordings remain protected. Development does not start from this chat.
