# Portable Work-Record Stamping Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with
> `superpowers:executing-plans` or `superpowers:subagent-driven-development`,
> using TDD and verification-before-completion.

**Goal:** Stamp each exact source work record from durable typed landing
evidence without scanning stores, guessing from bead IDs, overwriting
`gc.work_commit`, or introducing a refinery/watcher service.

**Architecture:** Stamping is an explicit, replayable core command invoked as an
ephemeral post-landing workflow step. A versioned landing receipt binds every
source record by canonical local store ref, bead ID, and source commit. Core
independently reads the already-recorded `delivery.landed` event, opens only the
named stores, verifies each current `gc.work_commit`, applies idempotent metadata
patches, and reads them back. Partial cross-store progress is recoverable by
replay; no cross-store transaction is claimed.

**Repositories:**

- Core: clean `gastownhall/gascity` rebuild descended from
  `8286ddfc47c4f8783258bcd5b471d1d3d74de26a`.
- Packs: clean `gastownhall/gascity-packs` branch containing verified
  publication (`c9fb1ad` or its merged descendant).

**Why this cannot safely use the current event unchanged:**

- `delivery.landed` currently carries `work_bead_ids` only.
- Gas City supports multiple city/rig stores, and bead IDs are not globally
  unique across those stores.
- The event does not bind a bead ID to its source `gc.work_commit`.
- Searching all stores or accepting the first matching ID would recreate the
  ambiguous topology this rebuild is intended to remove.

**Non-goals:** closing beads, changing `gc.work_commit`, publishing refs,
observing PR merges, adding MySQL/Dolt-server dependencies, or adding a
long-lived refinery actor.

## Durable contract

Add a v2 source-record identity:

```json
{
  "store_ref": "rig:example",
  "bead_id": "gc-123",
  "work_commit": "0123456789abcdef0123456789abcdef01234567"
}
```

Only canonical `city:<name>` and `rig:<name>` refs are accepted. The source
commit is the implementation worktree result and remains distinct from the
integrated/landed SHA.

Successful stamping adds this exact metadata without replacing source
provenance:

```text
gc.delivery_state=landed
gc.delivery_event_id=gcl-<64 lowercase hex>
gc.delivery_repository=<credential-free identity>
gc.delivery_target_ref=refs/heads/<branch>
gc.delivery_landed_sha=<observed landed SHA>
gc.delivery_verified_at=<event timestamp>
gc.delivery_source_commit=<unchanged gc.work_commit value>
```

### Task 1: Version source identity instead of guessing it

**Core files:**

- Modify: `internal/events/landing_payloads.go`
- Modify: `internal/events/landing_payloads_test.go`
- Modify: `internal/landing/landing.go`
- Modify: `internal/landing/landing_test.go`
- Modify: `cmd/gc/cmd_landing.go`
- Modify: `cmd/gc/cmd_landing_test.go`

**Pack files:**

- Create: `gascity/schemas/build/integration-manifest.v2.yaml`
- Create: `gascity/schemas/build/integration-result.v2.yaml`
- Modify: `gascity/assets/scripts/integrate_candidate.py`
- Modify: `gascity/assets/scripts/record_landing.py`
- Modify: `gascity/assets/workflows/integration-base/prepare-manifest.md`
- Modify: `gascity/tests/test_integrate_candidate.py`
- Modify: `gascity/tests/test_record_landing.py`

- [ ] Add failing core tests for a v2 receipt whose `work_records` contain
  canonical store refs, exact bead IDs, and 40-character source commits.
- [ ] Keep legacy v1 receipts readable and byte-compatible. Do not add required
  fields to a published v1 schema or silently reinterpret `work_bead_ids`.
- [ ] Add `WorkRecordRef` to the v2 canonical event identity so changing a
  store ref, bead ID, or source commit changes the deterministic `gcl-` ID.
- [ ] Reject duplicate `(store_ref, bead_id)` pairs, unsafe store refs, empty
  IDs, malformed commits, more than 256 records, and oversized receipts.
- [ ] Add pack v2 schemas. Require each source manifest row to carry the
  canonical source store ref and recorded `gc.work_commit`; propagate both into
  the integration result without deriving either from the worktree path.
- [ ] Make qualifying publication emit a v2 receipt. A v1 result may still land
  but is explicitly `not_stampable`; never scan stores to compensate.
- [ ] Prove with two fixture rigs containing the same bead ID that the v2 event
  preserves both exact identities and that swapping refs changes the event ID.

Commit core and pack changes separately. Do not mix repository histories.

### Task 2: Add an idempotent core stamping service

**Core files:**

- Create: `internal/workstamp/stamp.go`
- Create: `internal/workstamp/stamp_test.go`
- Modify: `internal/events/events.go`
- Create: `internal/events/work_stamp_payloads.go`
- Create: `internal/events/work_stamp_payloads_test.go`

- [ ] Write failing tests for `Stamp(ctx, eventID)` over in-memory city and rig
  stores. The service must load exactly one readable `delivery.landed` event.
- [ ] Resolve only the event's canonical store refs through the existing store
  topology resolver. Missing, remote, class, shadow, wildcard, or ambiguous refs
  fail closed.
- [ ] For every record, require the bead exists and current `gc.work_commit`
  equals the event's bound `work_commit`. A mismatch stamps nothing on that
  record and returns a deterministic conflict.
- [ ] Apply the full delivery metadata patch atomically per bead using one
  conditional update against its observed revision. Do not issue a sequence of
  independent metadata writes that could leave a false landed subset.
- [ ] Read every successful patch back before reporting it stamped.
- [ ] Record a deterministic `delivery.work_stamped` event per
  `(landing_event_id, store_ref, bead_id, work_commit)`. Replay returns
  `already_stamped=true` only when both bead metadata and the stamp event agree.
- [ ] Return a bounded result containing `stamped`, `already_stamped`, and
  `conflicts`. Cross-store partial success is allowed and must be replayable;
  never claim a distributed transaction.

### Task 3: Expose the explicit replay boundary

**Core files:**

- Modify: `cmd/gc/cmd_landing.go`
- Create: `cmd/gc/cmd_landing_stamp_test.go`
- Modify generated API/schema/docs files required by core checks.

Add:

```text
gc landing stamp --event gcl-<id> --json
```

- [ ] Require an exact `gcl-` ID and city context; never accept a receipt path
  as a substitute for a readable event.
- [ ] Emit exactly one JSON value with schema version, success state, counts,
  and per-record conflicts. Exit nonzero for unreadable event/store, identity
  mismatch, conditional-write conflict, or failed readback.
- [ ] Prove replay after injected failure resumes only unstamped records.
- [ ] Prove no command path pushes, opens PRs, closes beads, or invokes a
  networked SQL backend.

### Task 4: Add an ephemeral post-landing pack step

**Pack files:**

- Modify: build publication formulas and effective publish assets.
- Modify: `gascity/REQUIREMENTS.md`
- Modify: `gascity/formulas/REQUIREMENTS.md`
- Modify: `gascity/README.md`
- Modify: formula/derived compatibility tests.

- [ ] Add a post-landing `stamp-work-records` step routed to an ephemeral stock
  Gas City operator. It consumes only `gc.build.landing_event_id`.
- [ ] Invoke `gc landing stamp --event "$EVENT_ID" --json` and mirror its
  bounded result onto workflow metadata.
- [ ] Direct publication completes as landed before stamping begins. A stamp
  failure is `landing_recorded_stamp_pending`, not a rollback of the truthful
  landing event.
- [ ] PR publication does not stamp while `pending_external_merge`; disabled
  publication does not stamp.
- [ ] Derived pack overrides must preserve the new post-landing boundary.

### Task 5: Qualify stock, split-store behavior

- [ ] Use file-backed city and rig stores only; no MySQL, go-mysql-server, or
  Dolt SQL server.
- [ ] Test duplicate bead IDs in two rigs, missing rig, moved bead, changed
  `gc.work_commit`, already-stamped replay, partial two-store failure, and stale
  revision race.
- [ ] Assert `gc.work_commit` and `gc.work_base_commit` remain byte-identical.
- [ ] Assert no bead status or close reason changes.
- [ ] Run focused core packages, `make test-fast-parallel`, full pack tests,
  derived compatibility, Go tests, registry validation, schema/docs checks, and
  forbidden-capability audits.

## Exact next action

Start in a fresh core worktree. Add a failing test in
`internal/landing/landing_test.go` that submits two v2 work records with the
same bead ID in `rig:alpha` and `rig:beta`, then require both store refs and
source commits to participate in the deterministic event ID. Do not implement
stamping until this identity test is green.
