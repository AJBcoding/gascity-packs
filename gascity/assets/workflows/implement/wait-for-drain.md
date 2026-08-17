
Wait only on the core drain control bead and its `gc.drain_manifest.v1` rows.
Success requires the drain control to be closed with `gc.drain_state=succeeded`
and `gc.outcome=pass`, and every manifest row to have `status=succeeded` and
`outcome_kind=pass`, with every selected source anchor still open and carrying
its exact `gc.work_commit` plus `gc.delivery_state=integration_ready`. Failed,
skipped, abandoned, closed-as-shipped, or non-integration-ready source rows make
implement fail and write the aggregate summary.

Do not wait for or inspect downstream steps that depend on this bead, including
summarize, workflow-finalize, or root workflow closure; those cannot progress
until this bead closes. Do not close the input convoy head or the root workflow.
On success, close only this wait step with `gc.outcome=pass`. Summary path
override is {{summary_path}}.
