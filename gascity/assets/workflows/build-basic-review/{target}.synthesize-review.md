Synthesize the build-basic starter factory review.

Read the acceptance, test evidence, and simplicity review reports. Deduplicate
findings, preserve the source review lane for each finding, and classify each
item as required fix, missing evidence, or residual risk.

Also read `gc.build.code_review_context_path`. Carry each finding forward with
the reviewed candidate SHA/tree and its path from `## Integration Candidate`.
Use `## Source Provenance` only to identify which source must be revised on the
next attempt. Resolve relative filenames against the candidate, never the
launcher checkout or a source worktree. Required fixes must be specific enough
to create an unambiguous rework handoff.

Write one starter review synthesis under the build artifact root. The synthesis
must be short enough for a first-time factory user to scan, but concrete enough
for the fix lane to act without another planning pass.

Close with `gc.outcome=pass`,
`code_review.synthesis_path=<starter review synthesis path>`, and
`code_review.output_path=<starter review synthesis path>`.

Do not invoke provider-native subagents. Synthesis happens in this Gas City
fan-in lane.
