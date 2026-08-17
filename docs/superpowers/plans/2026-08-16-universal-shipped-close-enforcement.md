# Universal Shipped-Close Enforcement Implementation Plan

> **For agentic workers:** Execute only after portable work-record stamping is
> qualified. Use TDD and verification-before-completion for every close seam.

**Goal:** Make every supported Gas City mutation surface refuse a work record's
`shipped` close unless exact typed landing evidence is stamped on that exact
store-scoped bead and agrees with the event journal.

**Architecture:** Extend the existing core work-record close gate rather than
adding prompt-only rules. Move policy evaluation ahead of every routed and
passthrough close path, validate the stamped `gcl-` event against the bead's
canonical `(store_ref, bead_id, gc.work_commit)` identity, then make enforcement
the default. Control-plane step closure and non-shipped work outcomes remain a
separate contract.

**Dependency:** The portable stamping plan must first provide canonical store
refs, source-commit-bound landing events, atomic per-bead delivery stamps, and a
read API/service for verifying them.

## Existing seam and known gaps

Core already contains `cmd/gc/work_record_gate.go`:

- it recognizes task-like work records;
- it validates typed `gc.work_outcome`;
- for `shipped`, it currently proves only that `gc.work_commit` is reachable on
  `gc.work_branch`;
- it is warn-only unless `GC_WORK_RECORD_ENFORCE` is truthy;
- it runs after the by-ID class door, so routed closes can bypass it;
- direct raw `bd` execution is outside the `gc bd` gate.

Branch reachability is implementation provenance, not delivery evidence. It
must remain a useful check but cannot authorize `shipped`.

## Policy contract

The gate applies only when all of these are true:

- the target is a worker-claimable work record, not a workflow/check/drain/
  session/control bead;
- the prospective close sets `gc.work_outcome=shipped`;
- the mutation is performed through a supported Gas City managed surface.

Such a close requires:

```text
gc.work_commit=<40-char source commit>
gc.delivery_state=landed
gc.delivery_event_id=gcl-<64 lowercase hex>
gc.delivery_source_commit=<same value as gc.work_commit>
gc.delivery_landed_sha=<40-char observed landed commit>
```

The journal event identified by `gc.delivery_event_id` must be readable and
must bind the exact canonical store ref, bead ID, and work commit. Metadata by
itself is not authority.

`no-op`, `blocked`, and `abandoned` closures retain their existing reason
requirements and do not require landing. Ordinary graph-step closure uses
`gc.outcome`, not `gc.work_outcome`, and remains exempt.

### Task 1: Replace branch-only shipped validation with landing validation

**Core files:**

- Modify: `cmd/gc/work_record_gate.go`
- Modify: `cmd/gc/work_record_gate_test.go`
- Reuse: portable stamping/event verification service.

- [ ] Add failing unit tests proving a branch-reachable `gc.work_commit` without
  a delivery stamp cannot close as shipped.
- [ ] Add table tests for missing/malformed event ID, missing stamp fields,
  source-commit mismatch, landed-SHA mismatch, unreadable event, event bound to
  another bead, event bound to another store, and valid replay.
- [ ] Preserve the branch reachability check as a provenance diagnostic, but
  require both provenance and journal-backed landing evidence.
- [ ] Validate prospective metadata for atomic
  `gc bd update --status=closed --set-metadata ...` exactly as the current gate
  does. Never accept fields that the downstream `bd` command will not persist.

### Task 2: Put one policy in front of every managed close route

**Core files:**

- Modify: `cmd/gc/cmd_bd.go`
- Modify: `cmd/gc/cmd_bd_by_id.go`
- Modify: HTTP/API conditional mutation paths.
- Modify: graph/agent-script close executors where they bypass `gc bd`.
- Add focused route and split-topology tests.

- [ ] Extract a store-aware `WorkClosePolicy` that accepts the already-resolved
  canonical store ref, current bead, prospective metadata/status, and event
  reader.
- [ ] Invoke it before the by-ID class door returns, before the normal `bd`
  passthrough, before `update --status=closed`, before multi-ID close, and before
  API/store-backed work-record closure.
- [ ] Resolve dual residents through the same authoritative residency plan as
  the mutation. Never validate the retained work-store copy while writing the
  class-store copy.
- [ ] If the gate cannot read the authoritative bead, store, or event, fail
  closed for `shipped`; do not preserve the current best-effort skip.
- [ ] Keep non-work/control closes and non-shipped work outcomes behaviorally
  unchanged.
- [ ] Add parity tests proving CLI passthrough, routed by-ID, HTTP, graph worker,
  single close, batch close, and status-update forms return the same verdict.

### Task 3: Make enforcement default and migration explicit

**Core files:**

- Modify: config, doctor, help, and metrics surfaces associated with the work
  record gate.
- Add: a read-only audit command or doctor check.

- [ ] Replace opt-in `GC_WORK_RECORD_ENFORCE` behavior with enforced-by-default
  policy for shipped closes.
- [ ] During one bounded compatibility release, allow a clearly named
  warn-only migration setting only when explicitly configured. Emit telemetry
  and doctor output for every use; do not silently infer legacy mode.
- [ ] Provide a read-only audit that lists open/closed work records whose
  `gc.work_outcome=shipped` lacks a valid stamp, grouped by canonical store ref.
- [ ] Do not rewrite historical rows automatically. Remediation must either
  replay a valid landing stamp or reclassify an honestly non-shipped outcome.
- [ ] Remove the migration setting after the documented compatibility window
  and update generated CLI/config documentation.

### Task 4: Reconcile pack close vocabulary

**Pack files:**

- Modify: implementation/source close prompts in Gas City and all derived packs.
- Modify: `gascity/REQUIREMENTS.md`, formula ledgers, and compatibility tests.

- [ ] Inventory every `gc bd close`, `bd close`, and
  `update --status=closed` instruction.
- [ ] Keep workflow/check/drain/session closes on the control-plane
  `gc.outcome=pass|fail|skipped` contract.
- [ ] Source implementation completion must record provenance and an honest
  non-shipped lifecycle state. It must not set `gc.work_outcome=shipped` merely
  because implementation tests passed.
- [ ] Only the post-landing work-record transition may request a shipped close,
  and only after portable stamping succeeded for that exact record.
- [ ] Add derived-pack tests preventing BMAD, Compound Engineering,
  Superpowers, and gstack overrides from restoring branch-only shipped claims.

### Task 5: Define and test the raw-`bd` boundary honestly

`gc bd` can enforce managed mutations; a separately invoked upstream `bd`
binary can bypass `gc` unless the storage provider itself supports a policy
hook. Do not call enforcement “universal” until this boundary is resolved.

- [ ] Audit every supported write entrypoint and document direct raw `bd`
  mutation as either unsupported for managed cities or protected by a real
  provider-side pre-close hook.
- [ ] If upstream Beads exposes an atomic close-policy hook, implement and test
  it upstream, then consume it in Gas City.
- [ ] If no hook exists, make managed-city write guidance and generated agent
  environments route closing mutations through `gc bd`, and have doctor fail
  production enablement when an unguarded raw close path is configured.
- [ ] Do not use shell aliases, PATH shadowing alone, or prompt warnings as the
  security boundary.
- [ ] State the achieved scope precisely in release notes: all supported Gas
  City managed mutation surfaces, plus provider-side raw writes only if the
  upstream hook exists.

### Task 6: Stock-backend qualification and enablement gate

- [ ] Run the complete close matrix on file-backed and in-memory stores first.
- [ ] Cover city/rig split stores, duplicate bead IDs, class relocation,
  dual-resident migration, stale revisions, partial batch failure, event journal
  read failure, and already-closed replay.
- [ ] Prove no MySQL, go-mysql-server, or Dolt SQL server is started or required.
- [ ] Run core focused tests, `make test-fast-parallel`, pack/derived suites,
  API/schema/docs checks, registry validation, and a production capability
  audit.
- [ ] Enable enforcement only after the route-parity matrix is green and the
  audit reports no supported bypass.

## Exact next action

After portable stamping lands, add a failing
`cmd/gc/work_record_gate_test.go` case where `gc.work_commit` is reachable on
`gc.work_branch` but no `gc.delivery_event_id` exists. Require enforced shipped
close refusal. Then move that same case through the routed by-ID path before
changing the default enforcement mode.
