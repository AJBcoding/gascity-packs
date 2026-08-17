Run the BMAD story-development loop for the source-anchor worktree.

Use the `work_dir` already prepared by the inherited do-work lifecycle. The
child lanes replace BMAD quick-dev's native sub-agent/task handoff: implement
story, self-check, acceptance audit, and apply findings. Use the
implementation-review approval check to decide whether another loop iteration
is needed.

Require the inherited `gc.work_base_commit` before the child lanes edit the
source-worktree. After the approved loop produces its focused commit, record
the exact result `HEAD` as `gc.work_commit` on the source anchor. Never replace
that source commit with an integrated or landed commit.

Leave the source anchor open for the inherited compatibility submission step,
which records `gc.delivery_state=integration_ready` after readback. Never set `gc.work_outcome=shipped` from the focused branch, tests, self-check, or
acceptance audit.

Do not invoke provider-native subagents. Re-run or continue only through this
Gas City graph stage's child steps.
