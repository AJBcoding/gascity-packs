This is the deterministic `integration-base` candidate-assembly contract.
Concrete methodologies may override surrounding review policy, but must not
override the helper's Git decisions with ad-hoc commands.

From the launcher rig root, execute exactly once:

`.gc/scripts/integrate_candidate.py assemble --manifest "{{integration_manifest_path}}" --result "{{integration_result_path}}"`

Do not run manual merge, rebase, cherry-pick, push, PR, source-anchor close, or
target-ref commands before or after the helper. When the helper exits nonzero,
validate the typed result it emitted. Set this assembly step to
`gc.outcome=pass` whenever a validator-clean `ready`, `needs_rework`, or
`failed` result exists so `record-result` can persist and classify the evidence.
Set `gc.outcome=fail` only when no valid typed result exists. The following
`record-result` step blocks review and publication for non-ready outcomes.

Set the claimed step outcome before closing it. This role is on-demand and
must drain normally after routed work; it is not a persistent refinery.
