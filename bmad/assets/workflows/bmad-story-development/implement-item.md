Run the BMAD story-development loop for this shared-drain item.

The child lanes replace BMAD quick-dev's native sub-agent/task handoff:
implement story, self-check, acceptance audit, and apply findings. Use the
implementation-review approval check to decide whether another loop iteration
is needed.

Before the child lanes edit the shared source-worktree, record current `HEAD`
as this source anchor's `gc.work_base_commit` when absent. After the approved
loop, record the exact focused result commit as `gc.work_commit`. Never replace
that source commit with an integrated or landed commit.

Do not invoke provider-native subagents. Re-run or continue only through this
Gas City graph stage's child steps.
