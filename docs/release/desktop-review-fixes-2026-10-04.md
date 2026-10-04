# Desktop review-fix validation evidence

## Scope

Validated the Desktop qualification, recovery, and probe-cleanup changes on
code commit `83740c5f1dcc7fdd8992ea540992a10e2f223762`, against base
`082096a2fcaec7dd3ddf4f758ac0e31f0d83a605`. The evidence note is documentation
only; no code changed after these checks. No Python source files changed.

Environment: Linux `6.17.0-1022-azure` x86_64, Node.js `v22.23.3`, Python
`3.12.3`. Python checks used an isolated private `HOME` and `umask 0077`.
Router checks used isolated private `HOME`/XDG/Codex homes and `umask 0002`.

## Checks

| Command | Exit | Result |
| --- | ---: | --- |
| `python3 -m unittest discover -s server -p 'test_*.py'` | 0 | 283 total: 282 passed, 1 skipped |
| `python3 -m compileall -q server poc` | 0 | Passed |
| `python3 poc/eval_routing.py` | 0 | Passed |
| `npm run check` | 0 | Application validation and syntax checks passed |
| `node --test test/desktop-compatibility.test.mjs test/desktop-contract-probe.test.mjs test/desktop-launch.test.mjs test/desktop-provider-bridge.test.mjs` | 0 | 112 total: 109 passed, 3 skipped |
| `npm test` | 1 | 4,599 total: 4,532 passed, 27 failed, 40 skipped; completed without timeout |

The probe regressions were RED before implementation: unsolicited HTTP without
an expected qualification turn was classified as `DESKTOP_INCOMPATIBLE`, and
route-state initialization could not be injected before child launch. Both now
pass, along with app-server spawn-error propagation and private-home cleanup.
The previous immediate-PID-existence assertion also failed on base and now
passes with bounded process retirement checks.

## Full-suite baseline comparison

The exact-base full run used the same Linux/Node/Python/umask environment and
isolated home: `npm run check` exited 0; `npm test` exited 1 with 4,551 total
(4,482 passed, 28 failed, 41 skipped). Failure-name comparison found all 27
final-head failures on base and no head-only failures. The sole base-only
failure was `probe terminates a surviving native descendant before removing
its private home`, which depended on `kill(pid, 0)` immediately reporting
`ESRCH`.

The 22 shared Control Center failures include 18 tests that report
`Codex Router source root could not be located` and 4 descendant-drain/barrier
assertions. The candidate and base checkout both have group-writable trusted
source paths (`router`, `src`, and `bin` are `0775`; `src/control.mjs` is
`0664`; `bin/control` is `0775`). The unchanged `validSourceRoot` ownership
predicate rejects those modes. No permissions or ownership checks were
weakened or changed.

The remaining shared failures are two committed macOS recovery-journal tests
and three Vertex discovery tests. The Vertex tests fail with
`Provider host could not be resolved` in this environment. These same test
names and failures occur on exact base.

## Review and limits

A read-only integrated code/Python-specialist review of the final code commit
against base approved with no blocking findings. It reviewed 11 files across
the four code commits, found no Python changes, and checked installer/session
integration. The review task metadata selected `claude-opus-5.5`; the reviewer
could not independently verify the underlying model. It noted that native
metadata-command stderr can be included in a launch error; those commands run
with the probe's sanitized environment and private temporary home.

The automated code-review detector did not complete because its configured
model was unavailable. CodeQL reported no analysis because it detected no
changed analyzable-language files. An older dynamic Actions run targets
`5a97d7d349e84ad2e575c538942e5620438fac25`, not this code commit; its job log
was still reported in progress and its job-log request returned HTTP 404. No
Actions settings were changed.

Only portable Linux/fake-native coverage ran here. Signed macOS Desktop/native
acceptance remains unverified; the macOS-only network and real-native tests
were skipped. Strict codesign verification of the installed macOS app reports
its signature modified; the app was not modified, repaired, or restarted.
