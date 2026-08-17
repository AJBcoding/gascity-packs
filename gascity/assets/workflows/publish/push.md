
For direct mode (`push=true`, `open_pr=false`), push only the manifest candidate
SHA to the manifest target ref with the exact expected-object lease
`--force-with-lease=$TARGET_REF:$BASE_SHA`. Do not fall back to force, another
ref, or an implicit current branch. Fail closed if the remote cannot enforce the
lease. Re-read the target ref and require the candidate SHA.

After the lease-safe push and remote verification, invoke:

```bash
python3 .gc/scripts/record_landing.py record-direct \
  --integration-result "$INTEGRATION_RESULT_PATH" \
  --receipt "$ARTIFACT_ROOT/landing-receipt.json" \
  --gc-bin gc
```

Require the validated `gc landing record` result before publishing is complete.
On success record `gc.build.landing_status=landed`,
`gc.build.landing_event_id`, `gc.build.landed_sha`, and
`gc.build.landing_receipt_path`. On post-push failure record
`gc.build.publish_status=publication_pending` and
`gc.build.landing_status=verification_failed`, preserve the exact receipt, and
leave the step recoverable for identical replay.

Do not invoke `gc landing stamp` here. The formula's dependent
`stamp-work-records` step starts only after the publication path has recorded
its truthful landing state.
