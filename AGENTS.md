# ZIRU release and maintenance contract

This repository distributes an existing Jev implementation; preserve licenses
and the embedded runtime. The supported product installation is macOS Codex
Desktop, Node.js 22.19+, Python 3.11+. Never infer whole-product support from
the portable embedded router tests.

- Model policy and Jev decisions belong to `server/`; shared auth, transport and
  client integration belong to `router/`. Preserve full canonical replay.
- Use TypeSafe's direct API only. Never print, commit or republish credentials,
  raw transcripts, decision logs or installation backups.
- Test behavior changes RED → GREEN on isolated homes before implementation.
  Never use the owner's running service as a test fixture.
- Required checks: `python3 -m unittest discover -s server -p 'test_*.py'`,
  `python3 -m compileall -q server poc`, `python3 poc/eval_routing.py`, and
  `(cd router && npm run check && npm test)`.
- The owner disabled repository GitHub Actions on 2026-10-02. Remote CI is
  not a merge gate. Keep the local checks and integrated review above; merge
  reviewed candidates after those checks pass. Do not re-enable Actions
  without an explicit owner request.
- One integrated code and Python specialist review of changed behavior is
  required. Reviewers are read-only; the owner stages and commits.
- Installation uses the root transaction. Preserve unrelated settings and
  existing services. The user performs the final Desktop restart.
- Runtime state is private, outside the source. Keep the service checkout on
  stable internal storage. Exclude personal instructions and raw research logs.
- Record release evidence in `docs/release/`; reusable lessons belong in
  `docs/solutions/` only when not recoverable from code, tests or existing docs.
- Credits, subscription charges, API estimates and TypeSafe costs are distinct.
  Never claim savings from incomplete rates or fixed-token comparisons.
