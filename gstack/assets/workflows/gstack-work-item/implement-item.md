Implement the assigned gstack shared-drain item.

Gas City owns the shared drain and source-anchor lifecycle. Read only the
assigned item scope, implement the smallest complete change, run focused proof,
and record intended behavior, first verification command, changed files, proof
command, and remaining risks.

Before editing the shared source-worktree, record current `HEAD` as this source
anchor's `gc.work_base_commit` when absent. After the focused commit and proof
pass, record exact item `HEAD` as `gc.work_commit`. Never replace that source
result with an integrated or landed commit.

Record `gc.delivery_state=integration_ready` on the exact source anchor and
read it and `gc.work_commit` back. Leave the source anchor open for integration
and verified landing. Never set `gc.work_outcome=shipped` from the branch
commit, proof, or self-review. Only a later exact-record transition may request
shipped after portable post-landing stamping succeeds.

Close only this claimed workflow step with `gc.outcome=pass` after verification.

Do not invoke provider-native subagents. You are the single item lane.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
