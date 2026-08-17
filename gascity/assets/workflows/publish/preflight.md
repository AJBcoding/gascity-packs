
Validate auth, token scope, remote, branch names, PR base, collision policy,
protected/default targets, sanitized metadata, final report {{final_report}},
push authorization {{push}}, and open_pr authorization {{open_pr}}.

If either publication control is enabled, require
`gc.build.integration_result_path`, `gc.build.integration_result_hash`, and an
approved `gc.build.integration-result.v1` with `integration.outcome=ready`.
Require the recorded hash to match the file. Read the repository, artifact
root, remote, target ref, base SHA, and candidate SHA only through the result's
referenced manifest; never infer them from the current checkout.

Classify exactly one mode: direct is `push=true` and `open_pr=false`; PR is any
mode with `open_pr=true`; disabled is both false. Fail closed on missing or
ambiguous inputs before changing a remote ref.
