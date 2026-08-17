Optionally publish the gstack sprint.

Respect push {{push}} and open_pr {{open_pr}}. If neither is enabled, record a
no-op publish result. If publishing is enabled, verify the sprint report,
release readiness report, test evidence, and review approval are present before
any push or PR action.

Close with `gc.outcome=pass` and publish metadata.

Do not invoke provider-native subagents.

Enabled publication requires `gc.build.integration_result_path`,
`gc.build.integration_result_hash`, and `gc.build.final_report_path` on the
workflow root. Validate the approved ready integration result and publish only
its manifest remote, target ref, base SHA, candidate SHA, and artifact root.

Direct mode is exactly `push=true` and `open_pr=false`. Push the explicit
candidate with `--force-with-lease=$TARGET_REF:$BASE_SHA`, never force or an
implicit branch, then verify that the remote target equals the candidate. Only
after that verification run:

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
receipt or event ID or set a landed SHA; a trusted external merge observer owns
that transition.

When both controls are false, retain the successful no-op and also record
`gc.build.landing_status=not_requested`.

Do not invoke `gc landing stamp` from this publish step. Close publication only
after its truthful mode-specific landing state is recorded; the inherited
`stamp-work-records` step owns post-landing stamping and replay.
