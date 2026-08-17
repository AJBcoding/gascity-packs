# Gas City Pack Verified Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authorized direct publication consume the approved integration result, use an expected-object Git lease, and record exact typed landing evidence through `gc landing record`, while PR publication remains explicitly pending until an external merge is observed.

**Architecture:** Publication remains an ephemeral `gc.publisher` workflow step. A pack-owned `record_landing.py` adapter validates the immutable integration result and its manifest, constructs a bounded core receipt, and invokes the provider-neutral Gas City landing command after publication; it never pushes, opens a PR, stamps work, or closes beads. Direct mode is complete only after the returned `gcl-` event is recorded. Opening a PR is only `published`, not `landed`, and produces no landing receipt or event.

**Tech Stack:** Gas City graph-v2 TOML formulas and Markdown workflow assets, Python 3.11 standard library plus PyYAML, Git CLI, `gc landing record`, `unittest`/pytest.

**Spec:** `gastownhall/gascity@8286ddfc47c4f8783258bcd5b471d1d3d74de26a:engdocs/design/2026-08-16-ephemeral-integration-and-landing-contract.md`

## Global Constraints

- Work from clean pack base `0354ade93429d6c250b5cca587d035125e46e517` and clean core contract `8286ddfc47c4f8783258bcd5b471d1d3d74de26a`.
- The adapter must not execute `git push`, `gh pr`, `gc bd close`, `bd close`, MySQL, refinery, polecat, or Gastown commands.
- The only event-emission path is `gc landing record --receipt /absolute/path/landing-receipt.json --json`; generic `gc event emit` is forbidden.
- Direct publication requires `approved_candidate_sha == expected_landed_sha` and exact post-push observation by core.
- PR creation records `pending_external_merge`; it must not invoke the adapter or claim `landed`.
- A failed post-push observation leaves publication recoverable as `publication_pending`; replay must use the identical receipt and let core re-observe the remote.
- Work-record stamping, shipped-close enforcement, cleanup, and production enablement are outside this plan.
- Preserve `gc.work_commit` as worker-source provenance and do not close any source or workflow bead as shipped.
- Tests use disposable bare remotes and file fixtures only; no production ref or provider state may be touched.

---

### Task 1: Build a strict direct-landing receipt adapter

**Files:**

- Create: `gascity/assets/scripts/record_landing.py`
- Create: `gascity/tests/test_record_landing.py`
- Reuse: `gascity/assets/scripts/validate_build_artifact.py`
- Reuse: `gascity/tests/test_integrate_candidate.py`

**Interfaces:**

- Consumes: an absolute `gc.build.integration-result.v1` path whose `integration.outcome` is `ready`, the referenced validated manifest, and a `gc` executable.
- Produces: `build_direct_receipt(result_path: Path) -> dict[str, object]` and CLI `record-direct --integration-result PATH --receipt PATH [--gc-bin PATH]`.
- Produces this exact receipt field set: `workflow_id`, `integration_attempt_id`, `repository_path`, `repository`, `remote`, `target_ref`, `expected_target_sha`, `approved_candidate_sha`, `expected_landed_sha`, `publication_mode`, `integration_result_path`, `integration_result_hash`, `work_bead_ids`.

- [ ] **Step 1: Write the failing happy-path and replay tests**

Add tests that assemble a real integration result with `IntegrationRepositoryFixture`, push its candidate to the fixture target using test setup, and call the adapter with a temporary executable standing in for the external core boundary. The executable must read the receipt and return one JSON line:

```python
def test_record_direct_builds_exact_receipt_and_returns_core_result(self) -> None:
    fixture, result = assembled_ready_fixture(self.temp_root)
    candidate = integration_fields(result)["candidate_sha"]
    git(fixture.repository, "push", "origin", f"{candidate}:refs/heads/main")
    completed = run_adapter(
        "record-direct",
        "--integration-result", str(result),
        "--receipt", str(fixture.artifact_root / "landing-receipt.json"),
        "--gc-bin", str(fake_gc_executable(self.temp_root)),
    )
    self.assertEqual(completed.returncode, 0, completed.stderr)
    receipt = json.loads((fixture.artifact_root / "landing-receipt.json").read_text())
    self.assertEqual(receipt["workflow_id"], "build-test-001")
    self.assertEqual(receipt["integration_attempt_id"], "attempt-1")
    self.assertEqual(receipt["expected_target_sha"], fixture.base_sha)
    self.assertEqual(receipt["approved_candidate_sha"], candidate)
    self.assertEqual(receipt["expected_landed_sha"], candidate)
    self.assertEqual(receipt["publication_mode"], "direct")
    self.assertEqual(receipt["work_bead_ids"], ["task-a", "task-b"])
    self.assertRegex(json.loads(completed.stdout)["event_id"], r"^gcl-[0-9a-f]{64}$")
```

The replay test invokes the adapter twice, requires byte-identical receipt content, and accepts the second core result only when `already_recorded` is `true`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m pytest gascity/tests/test_record_landing.py -q
```

Expected: collection or assertion failure because `record_landing.py` and its CLI do not exist.

- [ ] **Step 3: Implement strict artifact and repository derivation**

Implement `record_landing.py` with these concrete rules:

```python
result = validate_build_artifact.validate_artifact_text(
    result_path.read_text(encoding="utf-8"),
    expected_schema="gc.build.integration-result.v1",
)
integration = result.front_matter["integration"]
if result.front_matter["status"] != "approved" or integration["outcome"] != "ready":
    raise LandingAdapterError("integration result must be approved and ready")

manifest_path = Path(integration["manifest_path"]).resolve(strict=True)
manifest = validate_build_artifact.validate_artifact_text(
    manifest_path.read_text(encoding="utf-8"),
    expected_schema="gc.build.integration-manifest.v1",
)
```

Require identical workflow mappings, producer attempt identity, base SHA, and the actual `sha256:` manifest hash recorded by the result. Require the result and manifest to resolve within the manifest artifact root. Require the repository and scratch worktree to be exact Git top levels, and require scratch `HEAD` to equal `candidate_sha`.

Resolve exactly one remote URL with:

```python
git -C "$REPOSITORY" remote get-url --all "$REMOTE"
```

Reject multiple URLs, control characters, and any HTTP(S) userinfo. Normalize local paths with `Path.resolve()` and preserve credential-free SSH/scp-like or HTTP(S) identities exactly. Never print a rejected URL.

- [ ] **Step 4: Implement atomic receipt creation and core invocation**

Serialize the receipt with sorted keys and a trailing newline. Write with mode `0600` using a same-directory temporary file plus `os.replace`. If the receipt exists, accept only byte-identical content; otherwise fail without overwriting it.

Invoke without a shell:

```python
[gc_bin, "landing", "record", "--receipt", str(receipt_path), "--json"]
```

Require exit zero, exactly one JSON value, `schema_version == "1"`, `ok is True`, a `gcl-` plus 64-lowercase-hex event ID, `observed_landed_sha == candidate_sha`, and boolean `already_recorded`. Emit the validated result as one JSON line on stdout. On failure, emit a credential-free error to stderr and return nonzero.

- [ ] **Step 5: Add negative tests and verify GREEN**

Add one focused test for each adapter-owned branch:

- result is blocked or not `ready`;
- manifest hash or workflow identity differs;
- result path, manifest path, repository, or scratch worktree is not absolute/contained as required;
- scratch `HEAD` differs from `candidate_sha`;
- remote URL is missing, ambiguous, or contains credentials;
- existing receipt differs;
- core exits nonzero, returns trailing JSON, returns a non-`gcl-` ID, or reports the wrong observed SHA.

Run:

```bash
python3 -m pytest gascity/tests/test_record_landing.py -q
python3 -m pytest gascity/tests/test_integrate_candidate.py gascity/tests/test_validators.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the adapter**

```bash
git add gascity/assets/scripts/record_landing.py gascity/tests/test_record_landing.py
git commit -m "feat(gascity): adapt integration results to landing receipts"
```

---

### Task 2: Make direct publication contingent on typed landing evidence

**Files:**

- Modify: `gascity/assets/workflows/build-base/publish.md`
- Modify: `gascity/assets/workflows/build-basic/publish.md`
- Modify: `gascity/assets/workflows/build-from-review-base/publish.md`
- Modify: `gascity/assets/workflows/publish/preflight.md`
- Modify: `gascity/assets/workflows/publish/push.md`
- Modify: `gascity/assets/workflows/publish/open-pr.md`
- Modify: `gstack/assets/workflows/gstack-build/publish.md`
- Modify: `gascity/tests/test_formula_assets.py`
- Modify: `gascity/tests/test_derived_pack_compatibility.py`

**Interfaces:**

- Consumes: root metadata `gc.build.integration_result_path`, `gc.build.integration_result_hash`, `gc.build.final_report_path`, `gc.var.push`, and `gc.var.open_pr`.
- Produces: direct state `gc.build.landing_status=landed`, `gc.build.landing_event_id`, `gc.build.landed_sha`, and `gc.build.landing_receipt_path` only after core returns success.
- Produces: PR state `gc.build.landing_status=pending_external_merge` with no receipt/event ID.

- [ ] **Step 1: Write failing publication-contract tests**

Add a table over the effective publish assets for `build-base`, `build-basic`, `build-from-review-base`, and `gstack-build`. Require every build publication surface to state all of these behaviors:

```python
required = (
    "gc.build.integration_result_path",
    ".gc/scripts/record_landing.py record-direct",
    "gc landing record",
    "gc.build.landing_status=landed",
    "gc.build.landing_event_id",
    "gc.build.landed_sha",
    "gc.build.landing_receipt_path",
    "gc.build.landing_status=pending_external_merge",
    "Opening a PR is published, not landed",
)
```

Also require the direct instructions to appear after lease-safe push verification, and require the PR branch to forbid `record_landing.py` and `delivery.landed` until a trusted external merge observer supplies the actual landed SHA.

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
python3 -m pytest gascity/tests/test_formula_assets.py gascity/tests/test_derived_pack_compatibility.py -q
```

Expected: failure naming missing landing metadata and adapter invocation.

- [ ] **Step 3: Strengthen preflight and direct-push instructions**

Require an approved integration result and exact candidate before any authorized build publication. Direct mode is exactly `push=true` and `open_pr=false`. Its push must name the manifest remote/target and use the recorded base as an expected-object lease; it may not fall back to force, a different ref, or an implicit current branch.

After push success, re-read the remote ref, then invoke:

```bash
python3 .gc/scripts/record_landing.py record-direct \
  --integration-result "$INTEGRATION_RESULT_PATH" \
  --receipt "$ARTIFACT_ROOT/landing-receipt.json" \
  --gc-bin gc
```

Parse the returned JSON and record the event ID and landed SHA on the workflow root and publish step. Do not record `publish_status=published` or close the publish step until this succeeds.

If the push succeeds but receipt recording fails, set `gc.build.publish_status=publication_pending`, `gc.build.landing_status=verification_failed`, preserve the receipt and integration result, and leave the step recoverable. Retry only with the identical receipt; core re-observes the remote on every retry.

- [ ] **Step 4: Make PR and disabled modes explicit**

For `open_pr=true`, push only the immutable candidate ref, open the PR, and record `gc.build.landing_status=pending_external_merge`. State exactly: `Opening a PR is published, not landed.` Do not call the adapter, do not create a landing receipt, and do not set a landing event ID. A later trusted merge-observer plan owns the actual post-merge SHA.

For `push=false` and `open_pr=false`, retain successful no-op behavior and add `gc.build.landing_status=not_requested`. No-op remains separate from workflow outcome.

- [ ] **Step 5: Verify formula and derived-pack compatibility**

Run:

```bash
python3 -m pytest gascity/tests/test_formula_assets.py gascity/tests/test_derived_pack_compatibility.py -q
go test ./...
```

Expected: all tests pass; inherited methodology packs preserve the base boundary and `gstack-build` preserves it through its override.

- [ ] **Step 6: Commit publication semantics**

```bash
git add gascity/assets/workflows gstack/assets/workflows/gstack-build/publish.md gascity/tests/test_formula_assets.py gascity/tests/test_derived_pack_compatibility.py
git commit -m "feat(gascity): require verified evidence after direct publish"
```

---

### Task 3: Reconcile requirements and user documentation

**Files:**

- Modify: `gascity/REQUIREMENTS.md`
- Modify: `gascity/formulas/REQUIREMENTS.md`
- Modify: `gascity/README.md`
- Modify: `gascity/tests/test_formula_assets.py`

**Interfaces:**

- Consumes: the direct/PR/no-op state machine from Task 2.
- Produces: the durable base-methodology compatibility contract for downstream pack authors.

- [ ] **Step 1: Write a failing requirements reconciliation test**

Require the behavior ledger to distinguish these terminal states:

```text
direct: published + landed + gcl event
pull request: published + pending_external_merge + no landing event
disabled: noop + not_requested
post-push verification failure: publication_pending + verification_failed
```

Require the formula row for `publish` to name `record_landing.py` and `gc landing record`, and require the README lifecycle to place verified landing after direct publication.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
python3 -m pytest gascity/tests/test_formula_assets.py -q
```

Expected: failure because current requirements describe only push/PR/blocked publication.

- [ ] **Step 3: Update the normative ledgers**

Change `GC-METH-BR-016` so authorized publication records push/PR status and applies the mode-specific landing rule. Add new behavior requirements for deterministic receipt replay and for PR non-landing. Update `GC-BF-018` so the internal helper owns preflight and publication only while delegating exact observation to core.

Document that `implement` has no typed integration result and therefore may not claim a shipped or landed outcome; its existing optional push is legacy/non-qualifying until a separate integration handoff is supplied.

- [ ] **Step 4: Update the README lifecycle**

Describe the healthy sequence as:

```text
integrate -> review -> finalize -> authorized publish -> verified landing
```

State that the publisher is ephemeral, direct mode requires a returned `gcl-` event, PR mode waits for a trusted merge observer, and neither mode closes shipped work in this phase.

- [ ] **Step 5: Verify and commit documentation**

```bash
python3 -m pytest gascity/tests/test_formula_assets.py -q
python3 scripts/validate_registry.py registry/index.yaml
git diff --check
git add gascity/REQUIREMENTS.md gascity/formulas/REQUIREMENTS.md gascity/README.md gascity/tests/test_formula_assets.py
git commit -m "docs(gascity): define verified publication states"
```

Expected: all commands pass.

---

### Task 4: Qualify the installed cross-process boundary

**Files:**

- Modify: `gascity/tests/test_ephemeral_integration_pipeline.py`
- Modify: `gascity/tests/test_record_landing.py`

**Interfaces:**

- Consumes: installed `.gc/scripts/record_landing.py`, a real disposable Git remote, and a contract-compatible temporary `gc` executable.
- Produces: pack-owned proof that only the exact approved candidate and receipt are handed to the core boundary after publication.

- [ ] **Step 1: Write the failing installed-path E2E test**

Extend the existing pipeline test to install `record_landing.py` beside `integrate_candidate.py`, assemble candidate B over base A, and simulate the authorized publisher with this exact test-only push:

```bash
git -C "$SCRATCH_WORKTREE" push "$REMOTE" \
  "$CANDIDATE_SHA:$TARGET_REF" \
  "--force-with-lease=$TARGET_REF:$BASE_SHA"
```

Use a contract-compatible temporary `gc` executable that captures `landing record --receipt ... --json`, independently reads the bare remote, rejects any receipt whose expected SHA differs, and emits a deterministic `gcl-` test result. Invoke the installed adapter twice.

Assert one unchanged receipt, two authoritative observations, second `already_recorded=true`, candidate ref at B, main at A, no other ref change, no `.beads` creation, and no invocation containing push, PR, close, MySQL, refinery, polecat, or Gastown commands.

- [ ] **Step 2: Run E2E and verify RED**

```bash
python3 -m pytest gascity/tests/test_ephemeral_integration_pipeline.py -q
```

Expected: failure because the installed landing adapter and publication assertions do not exist.

- [ ] **Step 3: Add only the missing installed wiring**

Copy the adapter into `.gc/scripts` in the fixture, make it executable, and route its `--gc-bin` to the contract executable. Do not add publication behavior to the integrator; publication remains a separate test setup action and workflow responsibility.

- [ ] **Step 4: Run the pipeline and mutation cases**

```bash
python3 -m pytest gascity/tests/test_ephemeral_integration_pipeline.py gascity/tests/test_record_landing.py -q
```

Then mutate candidate SHA, manifest hash, target ref, and core observed SHA one at a time. Each mutation must fail nonzero without replacing the original receipt or changing another ref.

- [ ] **Step 5: Commit qualification**

```bash
git add gascity/tests/test_ephemeral_integration_pipeline.py gascity/tests/test_record_landing.py
git commit -m "test(gascity): qualify verified publication handoff"
```

---

### Task 5: Run bounded final qualification and hand off the next boundary

**Files:**

- No production files expected.

**Interfaces:**

- Consumes: Tasks 1-4.
- Produces: merge evidence and the consumer inventory for work-record stamping and universal close enforcement.

- [ ] **Step 1: Run the full pack suite with resource evidence**

```bash
/usr/bin/time -l python3 -m pytest gascity/tests -q
/usr/bin/time -l python3 -m pytest tests/test_gascity_pack_inference_gate.py -q
go test ./...
python3 scripts/validate_registry.py registry/index.yaml
git diff --check
```

Record wall time, maximum RSS, peak memory footprint when available, and swaps.

- [ ] **Step 2: Run forbidden-capability audit**

```bash
rg -n -i 'git push|force-with-lease|gh pr|gc bd close|bd close|mysql|go-mysql-server|dolt sql-server|refinery|polecat|gastown' \
  gascity/assets/scripts/record_landing.py
```

Expected: no match. Publication workflow assets may contain lease-safe push and PR instructions; classify those separately as authorized pack-owned capability, never adapter capability.

- [ ] **Step 3: Inventory downstream consumers**

```bash
rg -n 'gc\.build\.landing_|gc\.build\.landed_sha|gcl-|record_landing|delivery\.landed|gc\.work_commit|gc\.work_outcome' \
  gascity gstack bmad compound-engineering superpowers tests docs
```

Use this inventory to write separate plans for portable work-record stamping and Beads close enforcement. Do not implement them in this branch.

- [ ] **Step 4: Verify branch state and report**

```bash
git status --short --branch
git log --oneline --decorate main..HEAD
```

Report the clean pack base/final SHA, exact remote/ref/base/candidate/event evidence, replay result, negative cases, suite metrics, and capability audit. State explicitly that the fixture alone was published, no production ref changed, and no bead was stamped or closed.
