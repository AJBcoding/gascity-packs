Run the BMAD story-development loop for this shared-drain item.

The child lanes replace BMAD quick-dev's native sub-agent/task handoff:
implement story, self-check, acceptance audit, and apply findings. Use the
implementation-review approval check to decide whether another loop iteration
is needed.

Before the child lanes edit the shared source-worktree, record current `HEAD`
as this source anchor's `gc.work_base_commit` when absent. After the approved
loop, record the exact focused result commit as `gc.work_commit`. Never replace
that source commit with an integrated or landed commit.

Record `gc.delivery_state=integration_ready` on the exact source anchor and
read it and `gc.work_commit` back. Leave the source anchor open for integration
and verified landing. Never set `gc.work_outcome=shipped` from the focused
branch, tests, self-check, or acceptance audit. Only a later exact-record
transition may request shipped after portable post-landing stamping succeeds.

Do not invoke provider-native subagents. Re-run or continue only through this
Gas City graph stage's child steps.
