This is the `build-from-convoy-base` integration handoff. After either
implementation drain finishes, expand the stock `integrate` contract with the
continuation artifact root and on-demand `{{integration_target}}`.

Require one validator-clean typed candidate result before `prepare-review`.
Do not let the continuation review source-worktree branches or summaries as if
they were one candidate. This stage remains shadow-only and has no publish,
landed, or shipped authority.
