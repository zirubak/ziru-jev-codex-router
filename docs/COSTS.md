# Measurement scope

Snapshot generated 2026-10-01 from local report output, selecting only policy
`split-v15-evidence-effort`. Recorded timestamps span 13:25:21–20:08:23; these
log timestamps do not carry a timezone, so no UTC claim is made. The source
contained 2,481 lines; 887 matched the policy. Raw logs and session identifiers
are excluded from distribution.

This is an observational call sample across five cache scopes, not a completed
project benchmark or a paired quality comparison. Seven attempts lack cache
usage. No current-policy technical fallback appeared in the aggregate gates;
failed/retried attempts and output/effort totals still require separate analysis.

Current model rates have not been independently verified for this release.
Therefore no currency estimate or overall savings percentage is published.
The bundled report retains historical rates and fixed-mix diagnostics; its
partial priced-subset percentages must not be interpreted as whole-sample
savings. In particular, its historical Sol baseline is not Sol 6.1.

For verified rates, cost on observed tokens would be:

`((input - cached_input) * input_rate + cached_input * cache_rate + output * output_rate) / 1,000,000`

Reasoning tokens are a subset of output and are not added twice. Model input
already includes tool output; do not bill the same tool text a second time.
Sum every recorded attempt, including failed attempts with reported usage, and
add separately metered TypeSafe decisions. Unknown usage or rates stay unknown.
Applying Sol or Astra prices to this same token stream is a fixed-token
counterfactual, not a real fixed-model run or an equal-quality comparison.

Official verification entry points: https://docs.typesafe.ai/llms.txt and
https://developers.openai.com/api/docs/pricing . Account-specific Codex credits
and monthly subscription charges must be checked separately. No additional
paid Sol/Astra comparison run was performed for this release.
