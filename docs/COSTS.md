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

Official API Standard rates were checked on 2026-10-01. They do not establish
account-specific Codex credit billing. No overall savings percentage is published
because output, context-tier, retry and TypeSafe billing coverage is incomplete.
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

## Conditional API comparison

Official source: https://developers.openai.com/api/docs/pricing . Standard,
short-context USD per million tokens, checked 2026-10-01:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GPT-6 Luna | $0.10 | $0.01 | $0.50 |
| GPT-6.1 Sol | $2.00 | $0.10 | $10.00 |
| GPT-6 Astra | $10.00 | $1.00 | $50.00 |

For an illustrative one million uncached input tokens plus 100,000 output
tokens, these rates yield $0.15 / $3.00 / $15.00 respectively. This is a
fixed-token arithmetic example, not an observed routing result. It excludes
TypeSafe decisions, cache writes, long-context uplift, retries, additional
verification and subscription charges. It cannot establish equal quality or
actual project savings. Long-context Standard rates are higher; use the
applicable tier from the source rather than applying this table indiscriminately.
