
If open_pr is {{open_pr}}, push only the immutable approved candidate ref and
create a PR only after that push succeeds and sanitized title/body from final
report {{final_report}} pass policy.

Opening a PR is published, not landed. Record
`gc.build.publish_status=published` and
`gc.build.landing_status=pending_external_merge`. This branch must not invoke
`record_landing.py`, create a landing receipt, set a landing event ID or landed
SHA, or emit `delivery.landed`. A later trusted external merge observer must
observe and supply the actual landed SHA.
