# Legacy Jev chat compaction repair

Existing chats with historical `jev/auto` or `jev/manual` turn metadata could
fail with `invalid_jev_selection` after selecting Jev again. Native pre-turn
compaction retains the previous turn model and the current provider headers.
The subsequent ordinary turn uses the supported `gpt-6.1-sol` carrier.

The router detects V1/V2 compaction before selection validation. Historical
Jev aliases are accepted only for compaction with the active bridge marker and
one valid Auto/Manual marker. The current marker selects the route, including
mode switches. Ordinary turns, unrelated models, malformed/duplicate markers,
recovery-only requests and unbridged historical aliases remain rejected.
Transport authentication precedes mapping. No history or selection is rewritten.

## Evidence and deployment boundary

- RED: isolated actual router HTTP returned 400 `invalid_jev_selection` rather
  than 200 for historical-alias compaction in both Desktop modes.
- Native reproduction: bundled engine emitted `model=jev/auto, mode=auto` for
  compaction followed by `model=gpt-6.1-sol, mode=auto` for the turn.
- Regression covers V1/V2, both historical aliases and active modes, ordinary
  alias turns, missing bridge marker, nonterminal trigger, unrelated model,
  malformed/duplicate marker, and existing recovery protection.
- Required local Node/Python/dossier checks and integrated specialist review
  apply. Deploy merged source through the root installation transaction.
- Production conversation is not a test fixture. Leave Desktop restart and
  actual existing-chat UI recovery to the user.

## Candidate verification

- Node syntax/application validation: PASS.
- Node suite: 4,574 PASS, 38 conditional SKIP, 0 FAIL.
- Python suite: 283 run, 1 optional SKIP, 0 FAIL.
- Python compile and 16 offline routing dossiers: PASS.
- Separate bundled-native fixtures: 4 PASS, 0 SKIP, 0 FAIL.
- Integrated code/Python specialist review: APPROVE, no actionable findings.
- Repository Actions remain disabled by the owner's policy; CI was not run.

Tracking: [issue 26](https://github.com/zirubak/ziru-jev-codex-router/issues/26).

Compound Engineering: No durable learning. Cause and boundaries are recoverable
from final code, regression fixtures, and this release record.
