
Resolve `<source-anchor-id>` using the same rules as `prepare-worktree`. Read `work_dir` from the source anchor and verify the implementation commit and
summary evidence are present in that worktree. Write per-item summary to
{{summary_path}} when set. If `summary_path` is not set, first use
`gc.implementation.summary_path` from the preceding implementation step when it
is present; otherwise use `{{artifact_root}}/task-<source-anchor-id>-summary.md`.

When reading beads with `gc bd show --json`, handle both an object and a
one-element list before reading metadata. `gc.work_dir` is the launcher rig
root, not the implementation worktree. If the source anchor `work_dir` is
missing, equals the launcher root, or points at a worktree without the exact
`gc.work_commit`, fail this step instead of submitting the source anchor.

On success, update only `<source-anchor-id>` with
`gc.delivery_state=integration_ready`, preserving its exact
`gc.work_base_commit`, `gc.work_commit`, worktree, and summary evidence. Read
the source anchor back with `gc bd show <source-anchor-id> --json` and verify
the delivery state and source commit are exact and its status remains open or
in_progress; if either check fails, fix the source anchor before closing this
step. Leave the source anchor open. Never set `gc.work_outcome=shipped` merely
because implementation tests passed; only a later exact-record transition may
request shipped after portable post-landing stamping has succeeded.

Then close only this claimed workflow step with `gc.outcome=pass`. Do not close
the source anchor, drain-unit convoy, parent convoy, or broader workflow root
from this step.
