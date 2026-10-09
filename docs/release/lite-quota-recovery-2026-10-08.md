# Responses-lite quota recovery

Issue: [#40](https://github.com/zirubak/ziru-jev-codex-router/issues/40).
Base: `01626596a18e8ff51cc688c2581d5a5b65c2b153`.

## Behavior and boundary

An account reset can restore native usage before the deadline stored in the
automatic quota state. Previously, Responses-lite requests returned HTTP 503
without contacting the native model until that deadline expired. Since external
adapters cannot preserve the lite replay contract, the cached state blocked the
only compatible execution path.

Responses-lite now sends each requested turn to the selected native model once.
Native success clears the automatic state; a fresh quota refusal updates the
state and returns the existing explicit HTTP 503 without external execution.
The manual dry marker retains priority, and ordinary Responses fallback is
unchanged. Input history, tools, protocol headers and Manual effort remain intact.
There is no timer, synthetic inference probe or internal retry loop.

This fixes cache-only refusal, not a live model quota restriction. An available
ordinary account allowance does not prove every selected model's bucket is
available. A selected native model that still returns a quota refusal continues
to return the explicit error.

## Candidate identity

| File | SHA-256 |
| --- | --- |
| `server/jev_server.py` | `2230de15786e1e6aff7cec3f1ab86884776e8b17b07234b84cb2b2765bdec4b8` |
| `server/test_selection_mode.py` | `e28856ace973f1b6478da8ef676f8923e5e5442480eef35ecf85a4c1efbf0bf4` |
| `server/test_lite_quota_recovery.py` | `be59b7a46884fe00f24d54742aa04ff0494fee23d08c5a531347ac714cfa5078` |

## Verification

- Pristine Python baseline: 353 tests, 352 PASS, 1 conditional SKIP.
- Local HTTP RED: the cached-quota matrix returned 503 with zero native
  attempts. The persisted-state suite produced 4 failing and 4 error subcases;
  the explicit manual-marker cases already passed.
- Focused GREEN: 3 persisted-state HTTP tests and 19 selection-mode tests passed.
- Full Python candidate: 356 tests, 355 PASS, 1 conditional SKIP.
- Python syntax: `python3 -m compileall -q server poc` passed.
- Offline routing dossier: `python3 poc/eval_routing.py` passed; no live judge call.
- Embedded router: `npm run check` passed; 4,670 tests, 4,627 PASS,
  43 conditional SKIP, 0 FAIL.
- Ruff on changed test modules, documentation links and whitespace passed.

Tests used isolated homes and localhost HTTP fixtures. The live service was not
used as a fixture. Skips do not establish Windows or Linux product support;
coverage was not measured. GitHub Actions remain disabled and no hosted CI
success is claimed.

Independent code and Python reviews passed on the candidate file hashes above;
no blocking findings remained. This source delivery
does not install the candidate, restart a service or establish Desktop UI recovery.
The root installation transaction and user-managed Desktop restart remain separate
from the repository merge.

No durable learning: the cause, boundary and regression are recoverable from the
code, tests and this release record.
