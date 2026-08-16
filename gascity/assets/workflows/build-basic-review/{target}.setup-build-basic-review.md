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

The review context must anchor every relative source path and verification
command to the assembled candidate, never the launcher checkout or an
individual source worktree. Read `gc.work_dir` only to identify the launcher rig
root and prove it differs from `scratch_worktree`. The context body must include
an `## Integration Candidate` section containing the absolute scratch path,
candidate SHA, tree SHA, manifest path/hash, and source map. If the candidate is
missing, not a Git worktree, equals the launcher root, or has drifted from the
recorded commit/tree identity, close setup with `gc.outcome=fail`.

Include an `## Source Provenance` section from the typed result so findings can
be routed back to the owning source on a later attempt. Source worktrees are not
code-review targets and their current contents cannot substitute for the
assembled candidate.

When writing artifact excerpts, append the actual file contents with commands
such as `cat "$REQUIREMENTS_PATH"` outside any quoted heredoc. Do not write
literal command substitutions such as `$(cat ...)` or `$(date ...)` into the
review context. Before closing this setup bead, verify the generated context
does not contain literal shell substitutions, for example with
`rg -n '\$\((cat|date)' "$CONTEXT_PATH"`; any match is a setup failure to repair
before setting `gc.outcome=pass`.

This starter factory intentionally uses only three review lanes so new users can
see fanout/fanin without a large reviewer roster.

Do not invoke provider-native subagents. Gas City graph lanes are the
delegation mechanism.

Close this setup bead with `gc.outcome=pass` only after the review context path
is recorded.
