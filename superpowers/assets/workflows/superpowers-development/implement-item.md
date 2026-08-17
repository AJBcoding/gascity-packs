Inspect the Superpowers shared-drain implementation task.

Resolve `gc.drain_member_id`, `gc.drain_item_index`, the existing shared
worktree, the approved requirements, approved plan, decomposition artifact, and
this task bead. The task bead describes the work unit only; the drained
Superpowers implementation workflow supplies the execution procedure.

Use the installed `executing-plans`, `test-driven-development`, and
`using-git-worktrees` skills as guidance for this task. Confirm the task can run
in the shared-drain lane, identify the first test behavior to drive, and write a
compact task context note for the following implementation steps.

Before any later step edits the shared source-worktree, record its current
`HEAD` on this source anchor as `gc.work_base_commit` when absent. Preserve that
base for the complete item lifecycle. The later result and submission steps
record the focused `gc.work_commit` and
`gc.delivery_state=integration_ready`. Leave the source anchor open. Never set `gc.work_outcome=shipped` from a passing test or task review.

Do not edit source files in the launcher checkout. Do not invoke
provider-native subagents or upstream plugin runtime commands.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
