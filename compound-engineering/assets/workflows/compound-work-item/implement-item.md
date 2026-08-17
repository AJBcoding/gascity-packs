Implement this Compound Engineering shared-drain item with {{implementation_target}}.

Run inside the existing shared worktree lifecycle. Resolve the assigned drain
member from metadata, validate ownership and context path {{context_path}} when
set, apply the smallest implementation changes for this item, run focused
verification, write an item summary to
`{{artifact_root}}/task-<source-anchor-id>-summary.md`, and close only this
claimed workflow step on success. Record the summary path, changed files, and
verification result on the source anchor before finishing the step.

Before editing the shared source-worktree, record its current `HEAD` as this
source anchor's `gc.work_base_commit` when absent. After the focused commit and
verification, record that exact item commit as `gc.work_commit`. Never replace
the source result with an integrated or landed commit.

Record `gc.delivery_state=integration_ready` on the exact source anchor and
read it and `gc.work_commit` back. Leave the source anchor open for integration
and verified landing. Never set `gc.work_outcome=shipped` merely because this
branch's tests passed; only a later exact-record transition may request shipped
after portable post-landing stamping succeeds.

Do not invoke provider-native subagents. This Gas City lane is the work
delegation mechanism for ce-work.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
