Use the built-in Gas City publish flow.

If publishing is enabled, publish the finalized build-basic result with the existing publish helper. If publishing is disabled, record a no-op publish outcome with the final artifact paths.

For build-basic, a finalized result can be an approved source anchor/worktree.
Do not mark publish failed or downgrade the workflow merely because the launcher
rig root was not mutated. When publishing is disabled, record a `noop` publish
result while preserving the approved build outcome.

`gc.outcome` is the workflow step outcome, not the publish mode. Never set
`gc.outcome=noop`. A disabled/no-op publish is a successful publish step:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'gc.publish_outcome=noop' \
  --set-metadata 'gc.publish_mode=disabled' \
  --set-metadata 'gc.build_outcome=pass' \
  --set-metadata 'gc.final_report=<final report path>' \
  --set-metadata 'gc.artifact_root=<artifact root>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Publishing disabled; build-basic result approved.'
```

Close only after the push, PR creation, or no-op publish result is recorded.

For any enabled publication, require the root metadata
`gc.build.integration_result_path`, `gc.build.integration_result_hash`, and
`gc.build.final_report_path`. Validate the approved ready integration result and
use only its manifest remote, target ref, base SHA, candidate SHA, and artifact
root. An approved source anchor/worktree without this typed handoff is not
eligible for qualifying publication.

Direct mode is exactly `push=true` and `open_pr=false`. Push the candidate SHA
explicitly to the target ref with the recorded base as
`--force-with-lease=$TARGET_REF:$BASE_SHA`; do not use force, a different ref,
or the current branch. Verify the remote target equals the candidate, then run:

```bash
python3 .gc/scripts/record_landing.py record-direct \
  --integration-result "$INTEGRATION_RESULT_PATH" \
  --receipt "$ARTIFACT_ROOT/landing-receipt.json" \
  --gc-bin gc
```

The adapter invokes `gc landing record`. Its validated one-line JSON result is
required before setting `gc.build.publish_status=published`,
`gc.build.landing_status=landed`,
`gc.build.landing_event_id=<event_id>`,
`gc.build.landed_sha=<observed_landed_sha>`, and
`gc.build.landing_receipt_path=<absolute receipt path>` on the workflow root and
publish step. If observation fails after push, instead record
`gc.build.publish_status=publication_pending` and
`gc.build.landing_status=verification_failed`, preserve the exact receipt and
integration result, and leave the step open for byte-identical replay.

When `open_pr=true`, push only an immutable candidate ref and open the PR.
Opening a PR is published, not landed. Record
`gc.build.publish_status=published` and
`gc.build.landing_status=pending_external_merge`. The PR branch must not invoke `record_landing.py` and must not emit `delivery.landed`. It must not create a
receipt or event ID or set a landed SHA; a trusted external merge observer owns
that transition.

When both controls are false, retain the successful no-op behavior above and
also set `gc.build.landing_status=not_requested`.
