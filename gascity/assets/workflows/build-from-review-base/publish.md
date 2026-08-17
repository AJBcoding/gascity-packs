This is the `build-from-review-base` publish stage.

Read push {{push}}, open_pr {{open_pr}}, and the finalized continuation outcome
from the workflow root metadata. If neither publishing action is explicitly
authorized, no-op and record `not_published`.

Publishing disabled or no-op status must never convert a blocked, failed, or
repairable finalization into a passing workflow outcome. Preserve
`gc.outcome=fail`, `gc.build.status=blocked`, `gc.failure_class`, and
`gc.restart.*` metadata when finalize recorded them.

If publishing is authorized, publish only after the continuation finalized
successfully and the review stage approved or explicitly allowed publication.
Record push status, PR status, or a blocked publish reason on the workflow root
and publish step before closing.

Enabled publication additionally requires root metadata
`gc.build.integration_result_path`, `gc.build.integration_result_hash`, and
`gc.build.final_report_path`, plus an approved ready typed integration result.
Publish only its manifest remote, target ref, base SHA, candidate SHA, and
artifact root.

Direct mode is exactly `push=true` and `open_pr=false`. Push the explicit
candidate to the target with
`--force-with-lease=$TARGET_REF:$BASE_SHA`, never force or an implicit branch,
and verify the remote target equals the candidate. Only after that verification
run:

```bash
python3 .gc/scripts/record_landing.py record-direct \
  --integration-result "$INTEGRATION_RESULT_PATH" \
  --receipt "$ARTIFACT_ROOT/landing-receipt.json" \
  --gc-bin gc
```

The adapter invokes `gc landing record`. Require its validated `gcl-` result
before recording `gc.build.publish_status=published`,
`gc.build.landing_status=landed`,
`gc.build.landing_event_id=<event_id>`,
`gc.build.landed_sha=<observed_landed_sha>`, and
`gc.build.landing_receipt_path=<absolute receipt path>` on the root and step. A
post-push failure is `gc.build.publish_status=publication_pending` plus
`gc.build.landing_status=verification_failed`; preserve the files and leave the
step recoverable for byte-identical receipt replay.

When `open_pr=true`, push only an immutable candidate ref and open the PR.
Opening a PR is published, not landed. Record
`gc.build.publish_status=published` and
`gc.build.landing_status=pending_external_merge`. The PR branch must not invoke `record_landing.py` and must not emit `delivery.landed`. It must not create a
receipt or event ID or set a landed SHA before a trusted external merge observer
supplies the actual landed SHA.

When both controls are false, record the existing no-op state and
`gc.build.landing_status=not_requested` without altering the finalized workflow
outcome.
