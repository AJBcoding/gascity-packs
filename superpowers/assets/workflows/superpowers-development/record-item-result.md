Record the Superpowers task result.

Update the per-item summary with changed files, test commands, command output
locations, commits to make, blockers, and traceability back to the plan task.
If the task could not be completed, record the blocker and leave the source
anchor open with a failing outcome instead of hiding the failure.

Create a focused commit for this task when the verification evidence is clean
and the repository state is ready. Use the approved plan's commit guidance when
it gives an exact message; otherwise use a concise message scoped to the task.

After the commit and final proof pass, record the exact source-worktree `HEAD`
on the source anchor as `gc.work_commit`. It remains the source result and must
not be rewritten to an integrated or landed commit.

Do not invoke provider-native subagents or upstream plugin runtime commands.
