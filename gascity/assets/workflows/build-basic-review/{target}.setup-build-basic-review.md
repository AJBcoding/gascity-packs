Prepare the build-basic starter factory review.

Gather the requirements, plan, decomposition, canonical implementation summary,
and the typed result at `gc.build.integration_result_path` into one review
context file under the artifact root. Require outcome `ready`; extract and
record its integration candidate `scratch_worktree`, `candidate_sha`,
`tree_sha`, manifest hash, source map, and verification records. Verify the
scratch worktree `HEAD` and tree still equal those immutable identities before
creating review lanes. Record the context path as
`gc.build.code_review_context_path`.

The integration candidate scratch_worktree is the only code review source of
truth. Source anchors and their `gc.work_commit` values are provenance inputs,
not independent review targets. The launcher rig root may remain unchanged in
this shadow phase; do not present that unchanged checkout as a review failure.

This starter factory intentionally uses only three review lanes so new users can
see fanout/fanin without a large reviewer roster.

Do not invoke provider-native subagents. Gas City graph lanes are the
delegation mechanism.

Close this setup bead with `gc.outcome=pass` only after the review context path
is recorded.
