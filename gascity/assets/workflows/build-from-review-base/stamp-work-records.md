This is the `build-from-review-base` `stamp-work-records` post-landing
boundary. It runs on the stock ephemeral `gc.run-operator` only after the
`publish` step has closed. Direct publication must therefore have already
recorded the truthful `gc.build.landing_status=landed` state and exact event ID
before this step begins. This step does not publish refs, observe remotes, or
close source work. Every continuation override must preserve this separate step
and its dependency on `publish`.

Use the claimed step ID and workflow root ID supplied by the standard claim
protocol. Write every mirrored key before closing by running `gc bd update`
with one `--set-metadata key=value` argument per key against both IDs. Close
only the claimed step with `gc bd close`; never close a source record here.

Read only `gc.build.landing_event_id` from the workflow root as stamping input.
Do not inspect publication artifacts or search work stores by bead ID. If the
event ID is absent, do not invoke a landing command. This is the expected path
for `pending_external_merge` and `not_requested`: mirror
`gc.build.work_stamp_status=not_requested` with zero counts on the workflow
root and this step, then close this step with `gc.outcome=pass`.

If the event ID is present, require it to be an exact lowercase `gcl-` ID and
invoke exactly:

```bash
gc landing stamp --event "$EVENT_ID" --json
```

Capture the single JSON result and exit status together. Validate
`schema_version=1`, the exact event ID, boolean `ok`, nonnegative integer
`stamped` and `already_stamped` counts, and the bounded `conflicts` array. Do
not copy the full JSON or conflict messages into bead metadata. Mirror only:

- `gc.build.work_stamp_event_id=$EVENT_ID`
- `gc.build.work_stamp_stamped=<stamped count>`
- `gc.build.work_stamp_already_stamped=<already_stamped count>`
- `gc.build.work_stamp_conflicts=<conflict count>`

When the command exits zero, require `ok=true` and no conflicts, set
`gc.build.work_stamp_status=stamped` on the workflow root and this step, then
close this step with `gc.outcome=pass`.

For a nonzero exit, malformed result, mismatched event ID, or any conflict,
preserve the already-recorded `gc.build.landing_status=landed`, publish status,
landed SHA, and event ID. Set
`gc.build.work_stamp_status=landing_recorded_stamp_pending`, mirror only counts
that passed validation (otherwise use zero), set this step's `gc.outcome=fail`,
and close it as failed with a concise replay instruction. Never rewrite the
landing event or describe the publication as rolled back. Recovery replays the
same exact command; core resumes only records not already stamped.
