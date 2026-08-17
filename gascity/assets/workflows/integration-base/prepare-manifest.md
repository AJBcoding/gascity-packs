This is the `integration-base` manifest-preparation methodology contract. A
concrete methodology may override source discovery, but it must preserve the
typed `gc.build.integration-manifest.v2` artifact and immutable source commit
meaning.

Resolve the workflow root from the claimed step's `gc.root_bead_id`. Resolve
the implementation convoy from root metadata
`gc.build.implementation_convoy_id` (fallback `gc.input_convoy_id`). Enumerate
only that convoy's source anchors in dependency order; do not discover work by
broad `gc bd list`, branch-name scans, or session history.

For every source anchor, require its canonical `gc.source_store_ref` in
`city:<name>` or `rig:<name>` form, exact bead ID, `gc.work_base_commit`,
`gc.work_commit`, its absolute authoritative `work_dir`, an absolute validated implementation-summary
path, a fresh `sha256:` summary hash, changed paths from
`git diff --name-only <base> <result>`, and source-anchor dependencies. Keep
`gc.work_commit` as both the source-worktree result and the manifest
`work_commit`; never derive the store ref from the worktree path or reinterpret
the source commit as an integrated or landed commit. Shared-drain items may name historical commits in
one worktree when their per-item base/result pairs and dependencies are intact.

Fail closed on missing metadata, a dirty source worktree, a summary hash
mismatch, or a result commit not reachable from the declared worktree.

Write Markdown with YAML front matter to `{{integration_manifest_path}}` under
`{{artifact_root}}`, using schema `gc.build.integration-manifest.v2`. Set the
repository to the launcher rig Git top level, remote to `origin`, target ref to
`refs/heads/main` unless root metadata declares another target, and base SHA to
the currently fetched target commit. Verification entries must be argv lists
copied from the approved plan, never shell strings.

Record the absolute path on the workflow root and claimed step as
`gc.build.integration_manifest_path`, then run
`GC_BEAD_ID=<claimed-step-id> .gc/scripts/checks/build-artifact-valid.sh` from
the launcher rig root. On repair, preserve validated source SHAs. Close only
after setting `gc.outcome=pass`. An override must not push, publish, close
source anchors, or claim that the candidate landed.
