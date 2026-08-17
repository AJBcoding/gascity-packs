This is the `build-base` publish stage and the complete virtual publication
contract. Concrete overrides must preserve every boundary below.

Read `gc.build.integration_result_path`, `gc.build.integration_result_hash`,
`gc.build.final_report_path`, `gc.var.push`, and `gc.var.open_pr` from the
workflow root. Any enabled publication requires an approved
`gc.build.integration-result.v2` with `integration.outcome=ready`; use its
manifest remote, target ref, base SHA, candidate SHA, and artifact root exactly.
The recorded result hash must equal the file's actual hash. Never substitute a
worktree HEAD, current branch, or launcher-rig ref.
Legacy v1 results remain recordable, but their adapter result is explicitly
`work_record_stampability=not_stampable`; never scan stores to compensate.

There are exactly three modes:

1. Direct mode is `push=true` and `open_pr=false`. Push only the approved
   candidate to the manifest target with an expected-object lease equivalent to
   `--force-with-lease=$TARGET_REF:$BASE_SHA`; never fall back to force, another
   ref, or an implicit current branch. Verify that the remote target now names
   the candidate. Only then run:

   ```bash
   python3 .gc/scripts/record_landing.py record-direct \
     --integration-result "$INTEGRATION_RESULT_PATH" \
     --receipt "$ARTIFACT_ROOT/landing-receipt.json" \
     --gc-bin gc
   ```

   The adapter calls the provider-neutral `gc landing record` boundary. Parse
   its one-line JSON result. Only a successful returned `gcl-` event permits
   `gc.build.publish_status=published`, `gc.build.publish_action=push`,
   `gc.build.landing_status=landed`,
   `gc.build.landing_event_id=<event_id>`,
   `gc.build.landed_sha=<observed_landed_sha>`, and
   `gc.build.landing_receipt_path=<absolute receipt path>` on both the workflow
   root and this step.

   If the push succeeds but recording fails, set
   `gc.build.publish_status=publication_pending` and
   `gc.build.landing_status=verification_failed`. Preserve the integration
   result and receipt, leave this step open and recoverable, and retry only with
   the byte-identical receipt so core re-observes the remote.

2. PR mode is any mode with `open_pr=true`. Push only an immutable candidate
   ref, then open the PR using sanitized final-report material.
   Opening a PR is published, not landed. Record
   `gc.build.publish_status=published`, `gc.build.publish_action=pr`, and
   `gc.build.landing_status=pending_external_merge`. This branch must not invoke `record_landing.py` and must not emit `delivery.landed`. It must not create a
   landing receipt, set a landing event ID, or set a landed SHA. A later trusted
   merge observer must supply the actual landed SHA.

3. Disabled mode is `push=false` and `open_pr=false`. Record
   `gc.build.publish_status=noop`, `gc.build.publish_action=noop`,
   `gc.build.landing_status=not_requested`, the reason
   `push=false_open_pr=false`, and remote presence. This is a successful no-op,
   separate from the workflow's build outcome.

Write the mode-specific publish result under the artifact root and mirror its
metadata on the workflow root and this step. Close this step only after the
direct landing event, PR-pending state, or explicit disabled state is recorded.
Do not invoke `gc landing stamp` from this publish step. The dependent
`stamp-work-records` step owns that replayable boundary after publication has
truthfully completed as landed, pending external merge, or not requested.
