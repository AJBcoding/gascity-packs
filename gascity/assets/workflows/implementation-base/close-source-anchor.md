This is the `implementation-base` methodology contract source-anchor
submission step. The stable step id remains `close-source-anchor` for formula
compatibility, but this step does not close the source work record.

Concrete methodology packs override this step only when they need additional
artifact checks. Verify `gc.work_base_commit`, the focused `gc.work_commit`,
and the implementation summary, then record
`gc.delivery_state=integration_ready` on the source anchor. Leave the source
anchor open so integration, verified publication, and portable stamping can
run. Never set `gc.work_outcome=shipped` from implementation or test evidence.
If `{{summary_path}}` is set, write or verify the per-item implementation
summary there before closing only this claimed workflow step with
`gc.outcome=pass`.
