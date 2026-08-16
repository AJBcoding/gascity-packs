Apply build-basic starter review findings.

Read the starter review synthesis and the typed integration result recorded in
the review context. Verify that the reviewed `scratch_worktree`, `candidate_sha`,
and `tree_sha` still identify the exact same integration candidate.

This shadow phase must not mutate that candidate, a source worktree, or the
launcher rig root. If all three review lanes approve the exact candidate, write
a no-op review summary and set `code_review.verdict=done`. If required fixes or
missing evidence remain, write a structured rework handoff containing the
candidate SHA and tree, the integration manifest hash and source map, each
finding, and the smallest required source change. Set
`code_review.verdict=iterate`. The caller must apply fixes to the relevant
source, then create a fresh manifest and a fresh immutable integration result;
never reuse a stale result after source changes.

Set `code_review.verdict=done` only when acceptance, test evidence, and
simplicity all approve after this pass. Set `code_review.verdict=iterate` when
required fixes remain.

Always close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<starter review summary path>`, and
`code_review.output_path=<starter review summary path>`.

Use the exact claimed bead id when updating metadata. Do not pass freeform notes
or additional positional arguments to `bd update`; unquoted words can resolve to
unrelated beads. Use this command shape:

```bash
bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.verdict=done' \
  --set-metadata 'code_review.report_path=<starter review summary path>' \
  --set-metadata 'code_review.output_path=<starter review summary path>'
bd close "$CLAIMED_BEAD_ID" --reason 'Build-basic starter review approved.'
```

Do not invoke provider-native subagents. This starter factory graph lane is the
fix delegation mechanism.
