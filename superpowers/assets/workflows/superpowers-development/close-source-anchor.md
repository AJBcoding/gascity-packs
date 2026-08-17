Submit the Superpowers implementation source anchor for integration. The
stable step id remains `close-source-anchor`, but it does not close source work.

Resolve the source anchor using the same rules as the inherited worktree setup.
Read `work_dir`, verify the task summary exists, verify the exact
`gc.work_commit` exists in and is reachable from that worktree, and confirm the
source anchor still matches the current drained item.

On success, record `gc.delivery_state=integration_ready` on the exact source
anchor and read the state and source commit back. Leave the source anchor open
for integration and verified landing. Never set `gc.work_outcome=shipped` from
the branch commit, passing tests, or task-review approval. Only a later
exact-record transition may request shipped after portable post-landing
stamping succeeds.

Close only this claimed workflow step with `gc.outcome=pass`. Do not close the
source anchor, drain-unit convoy, parent convoy, workflow root, or
post-implementation review steps.

Do not invoke provider-native subagents or upstream plugin runtime commands.
