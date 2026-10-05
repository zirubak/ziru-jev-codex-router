# Native local checkpoint compaction follow-up

Historical Jev chats could still fail after PR 27. The bundled native engine
uses ordinary `/responses` for local checkpoint summarization when historical
model metadata has no remote-compaction support. Its terminal item is a user
checkpoint-summary prompt with empty tools, rather than `compaction_trigger`.
The previous native fixture responded directly and did not traverse the router.

Recognize the measured native default checkpoint-summary shape only: terminal
single user `input_text` beginning with the native checkpoint prefix, empty
explicit tools, automatic tool choice, and no deferred tool declarations.
The historical-alias allowance additionally requires the active bridge and a
single valid current Auto/Manual marker. Ordinary alias turns, unrelated models,
malformed markers, recovery-only traffic and summaries with executable tools
remain refused. Native local summaries can carry `reasoning.effort=auto` even
under Manual; that placeholder is replaced only with the current confirmed
owner-only Manual selection, identified by matching native thread/cache IDs.
Pending, missing, corrupt, mismatched and unsupported selections fail before
upstream dispatch. The state reader opens existing metadata without creating
it. Effort-only turn changes are covered through the actual native pipeline.
This local native path retains an ordinary text response; V1/V2
remote compaction protocols retain their existing response contracts.

The known default prompt is supported. Arbitrary custom `compact_prompt` values
are outside this recognition contract. No conversation, goal or private route
metadata is rewritten; the installed live service is not a test fixture.

## Verification contract

The native fixture now sends actual bundled-engine HTTP through an isolated
actual router and synthetic upstream. It covers historical Auto/Manual crossed
with selected Auto/Manual and observes completed compaction and the next turn.
A baseline-source switch lets the same fixture reproduce the prior failure.
The synthetic upstream invokes the actual Python selection policy before
responding. HTTP regression also pins ordinary-text output, complete canonical replay,
mode mapping, and refusal cases; classifier unit coverage is measured separately.
Required full local checks and one integrated code/Python review remain gates.

## Candidate verification

- Native actual-router/Python-selection fixture: 7 PASS, no SKIP/FAIL.
- Focused HTTP regression: 2 PASS; classifier 100% line/branch/function coverage.
- Final full Node suite: 4,609 PASS, 41 conditional SKIP, 0 FAIL.
- Python suite: 283 run, 1 optional SKIP, 0 FAIL; compile and 16 dossiers PASS.
  Unchanged Python evidence was reused after the final JavaScript correction.
- Integrated code/Python review: initial Manual HIGH corrected; final APPROVE.
- GitHub Actions remain disabled under owner policy; no remote CI was run.

Tracking: [issue 28](https://github.com/zirubak/ziru-jev-codex-router/issues/28),
follow-up to [PR 27](https://github.com/zirubak/ziru-jev-codex-router/pull/27).
Desktop restart and production-chat UI recovery remain user verification.

Compound Engineering: No durable learning. The fixture regression and this
release record preserve the wire-format and verification applicability.
