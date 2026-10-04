# Desktop review-fix validation evidence

## Scope

Validated the Desktop qualification, recovery, and probe-cleanup changes on
code commit `c8b7e30aedb638f73b8b5b55a9e4671358b2ef43`, against base
`082096a2fcaec7dd3ddf4f758ac0e31f0d83a605`. The evidence note is documentation
only; no code changed after these checks. No Python source files changed.

Environment: Linux `6.17.0-1022-azure` x86_64, Node.js `v22.23.3`, Python
`3.12.3`, router dependencies from `npm ci`. Python checks used an isolated
private `HOME` and `umask 0077`. Router checks used isolated private
`HOME`/XDG/Codex homes and `umask 0002`. Head and base ran sequentially.

## Checks

| Command | Exit | Result |
| --- | ---: | --- |
| `python3 -m unittest discover -s server -p 'test_*.py'` | 0 | 283 total: 282 passed, 1 skipped |
| `python3 -m compileall -q server poc` | 0 | Passed |
| `python3 poc/eval_routing.py` | 0 | Passed |
| `npm run check` | 0 | Application validation and syntax checks passed |
| `node --test test/desktop-contract-probe.test.mjs` | 0 | 19 total: 17 passed, 2 skipped |
| `npm test` | 1 | 4,604 total: 4,537 passed, 27 failed, 40 skipped; completed without timeout |

The responder regressions were RED before implementation: two overlapping
requests whose headers arrived before their bodies both received HTTP 200 for
one expected turn; a request whose turn changed before its body arrived was
served; and an automatic `/v1/responses/compact` request during an expected
turn became recoverable `DESKTOP_INCOMPATIBLE`. The responder now reserves the
turn synchronously, rechecks turn ownership after the body, and rejects
automatic compaction as a safety failure before contract verification. The
tests confirm these errors are rethrown by `planQualifiedDesktopLaunch`, and
that an ordinary supported response and the intentional recovery compaction
refusal still succeed.

## Full-suite baseline comparison

The exact-base full run used the same environment: Python checks and
`npm run check` exited 0; `npm test` exited 1 with 4,551 total (4,483 passed,
27 failed, 41 skipped). Failure-name comparison found the same 27 names on
both revisions, with no head-only or base-only failures.

The 22 shared Control Center failures include tests that report
`Codex Router source root could not be located` and descendant-drain/barrier
assertions. The checkout has group-writable trusted source paths (`router` and
`router/src` are `0775`), which the unchanged `validSourceRoot` ownership
predicate rejects. No permissions or ownership checks were weakened or changed.

The remaining shared failures are two committed macOS recovery-journal tests
and three Vertex discovery tests that fail with `Provider host could not be
resolved` in this environment. The full suite is therefore not a clean pass.

## Review and limits

A read-only integrated code/Python-specialist review of `c8b7e30` (incremental
diff from `d9d8a36`, plus the whole diff from base) approved with no findings.
It confirmed no Python files changed, that duplicate, stale and compaction
requests cannot become `DesktopContractMismatch`, that the recovery refusal is
unchanged, and that reservations do not leak into the native turn flow; the
five new responder tests passed in five repeated runs. Task metadata selected
`claude-opus-5.5`; the reviewer reported only "Claude (Anthropic)". An earlier
review noted that recovery for an incompatible native build relies on that
build retaining the configured recovery headers; that refusal path was not
independently exercised against a mismatched real build.

The automated code-review detector on `c8b7e30` again failed because its
configured model was unavailable, so its empty result is not a review. CodeQL
reported that it performed no analysis. The only Actions runs for this head
are dynamic Copilot agent sessions, not repository CI; no Actions settings
were changed.

Only portable Linux/fake-native coverage ran here. Signed macOS Desktop/native
acceptance remains unverified; the macOS-only network and real-native tests
were skipped. Strict codesign verification of the installed macOS app reports
its signature modified; the app was not modified, repaired, or restarted.

## Follow-up: stale malformed request bodies

Code commit `3f39c9338b326d5065b03eec84fb944a981bcd3c` (parent `aebcdb2`)
moves the responder's turn-ownership check ahead of JSON parsing. A request
whose expected or recovery turn changed while its body was pending, or that
arrives after a failure is already recorded, now hard-stops as a safety error
whether its body is valid or malformed. The earlier recorded error is kept.
Only `router/src/desktop-contract-probe.mjs` and its test changed.

Three regressions were RED on `aebcdb2`: they cover a stale expected turn, a
changed recovery turn, and a previously recorded safety error, each with a
malformed body. In each case the old code reported `DesktopContractMismatch`.
They are GREEN on `3f39c93`, and the tests confirm the errors are not
`DesktopContractMismatch`/`DESKTOP_INCOMPATIBLE` and that
`planQualifiedDesktopLaunch` rethrows them. Ordinary response, duplicate,
valid-body stale, unexpected-compaction and recovery-refusal tests still pass.

Environment: Linux x86_64, Node.js `v22.23.3`, Python `3.12.3`.

| Command | umask | Exit | Result |
| --- | --- | ---: | --- |
| `python3 -m unittest discover -s server -p 'test_*.py'` | 0077 | 0 | 283 total: 282 passed, 1 skipped |
| `python3 -m compileall -q server poc` | 0077 | 0 | Passed |
| `python3 poc/eval_routing.py` | 0077 | 0 | Passed |
| `npm run check` (after `npm ci`) | 0022 | 0 | Passed |
| `node --test test/desktop-contract-probe.test.mjs` | 0002 | 0 | 24 total: 22 passed, 2 skipped (4 repeated runs) |
| `npm test` (after `npm ci`) | 0022 | 1 | 4,607 total: 4,554 passed, 13 failed, 40 skipped |

An initial `npm test` without `npm ci` had 579 failures, mostly
`Cannot find package` errors, so it is not counted. The 13 failures are 10 in
the Control Center harness/Electron suites, including `Codex Router source root
could not be located` (the `router` checkout directories are `0775`), and three
Vertex discovery tests that need provider DNS. Rerunning those three files with
only the two changed files reverted to `aebcdb2` produced the same 13 failures
(108 total: 94 passed, 13 failed, 1 skipped). This suite is not a clean pass.

The integrated read-only code and Python-specialist review of
`aebcdb2..3f39c93` approved with no findings and confirmed that no Python files
changed. The task requested `claude-opus-5.5`, but the reviewer could not
confirm which backend model it ran on. Signed macOS Desktop acceptance was not
run.
