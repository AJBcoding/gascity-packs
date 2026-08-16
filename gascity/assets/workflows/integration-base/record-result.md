This is the `integration-base` result-recording methodology contract. Concrete
methodologies may override reporting, but must preserve the validated result
path, hash, outcome, candidate commit, and tree identity.

Require `{{integration_result_path}}` to validate as
`gc.build.integration-result.v1`. Compute its `sha256:` hash and record
`gc.build.integration_result_path`, `gc.build.integration_result_hash`,
`gc.build.integration_outcome`, `gc.build.integration_candidate_commit`, and
`gc.build.integration_tree` when present on the workflow root.

Verify the manifest path/hash matches `{{integration_manifest_path}}`, every
safety flag is false, and the target ref still resolves to the manifest base.
Only `ready` may pass. For `needs_rework` or `failed`, set `gc.outcome=fail`;
do not close the root, source anchors, or candidate as shipped. An override
must preserve these evidence and blocking semantics.
