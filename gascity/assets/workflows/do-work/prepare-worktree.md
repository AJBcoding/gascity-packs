
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that do-work root with `bd show <root-bead-id> --json`.
2. Resolve `<source-anchor-id>` from the do-work root:
   - read root metadata `gc.input_convoy_id`; hard-fail if it is missing
   - verify `gc.input_convoy_id` matches rendered runtime convoy `{{convoy_id}}`
   - read that input convoy with `bd show <input-convoy-id> --json`
   - if input convoy metadata has `gc.synthetic_kind=drain-unit-convoy`, use
     input convoy metadata `gc.drain_member_id`
   - do not use the synthetic drain-unit convoy id as `<source-anchor-id>`;
     hard-fail if the selected source anchor id equals the synthetic input convoy id
   - otherwise use `<input-convoy-id>` as the source anchor
   - if root metadata also has `gc.drain_member_id`, it must match the selected
     drain member
3. Validate context path {{context_path}}, files ownership, and verification
   policy for the resolved source anchor.
4. Create or reuse a deterministic git worktree at
   `$(pwd)/worktrees/<source-anchor-id>`. If the path is missing, run
   `git worktree add "$WORKTREE" --detach HEAD`. If the path exists but is not
   the worktree for this repository, fail closed.
5. Before implementation edits, resolve worktree `HEAD` as the immutable item
   base. If `gc.work_base_commit` is absent, persist that 40-character SHA; if
   present, verify it is an ancestor of `HEAD` and do not overwrite it.
6. Persist the absolute path and base on the source anchor with
   `bd update <source-anchor-id> --set-metadata work_dir=<absolute worktree path> --set-metadata gc.work_base_commit=<base SHA>`.
   For synthetic drain-unit convoys, never persist `work_dir` on the synthetic drain-unit convoy; the original drain member/source anchor is authoritative.
   Verify the source anchor now has `work_dir` and `gc.work_base_commit` before closing this step with
   `gc.outcome=pass`.
