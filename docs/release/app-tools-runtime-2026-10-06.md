# Trusted Desktop app tool runtime

Status: local checks, integrated review and root installation passed. The
post-restart fresh-chat gate remains pending.

## Candidate and scope

- Branch: `codex/fix-app-tools-runtime`; baseline: `1921822`.
- Use the OpenAI-signed app bundle Node for the Desktop bridge and launcher.
- Export `CODEX_MCP_NODE_PATH` and register the same executable in the supported
  `codex-app-tools@openai-bundled` plugin MCP environment override.
- Preserve unrelated configuration and reject foreign runtime ownership before
  installation writes. Retain the existing root snapshot/restore transaction.
- No public API change, app bundle edit, app restart, or remote push.

## Verification

- RED: the installation test observed `/bin/node` instead of `/signed/node`.
- GREEN: isolated Desktop tests passed, including configuration preservation,
  repeated installation, ownership conflict rejection and root restoration.
- Actual `/Applications/ChatGPT.app` signature/contract check passed; bundled
  Node reports `v24.21.0` and validates against OpenAI Team ID `2DC432GLL2`.
- Python discovery: 290 tests, zero failures, one existing optional signed-app
  test skipped. The real signed-app focused run passed all 28 tests separately.
- `python3 -m compileall -q server poc`: passed.
- `python3 poc/eval_routing.py`: passed all 16 routing fixtures.
- `npm run check`: passed syntax and seven application manifest checks.
- `npm test`: 4,656 tests; 4,613 passed, 43 skipped, zero failed/cancelled.
- Changed Python files: `ruff check` passed. `git diff --check` passed.
- Integrated code and Python specialist review: approved, no actionable findings.
- Test coverage percentage was not measured; the coverage package is unavailable.

## Installation and terminal evidence

- Root installation exited successfully; its transaction receipt is committed.
- Config and both launchers were read back and use the signed bundle runtime.
  Unrelated parsed config matched the pre-install snapshot.
- Git commit identity and local main ancestry are verified in the delivery
  response after this record is committed.
- Fresh-chat tool listing and read operation after the owner reopens Desktop:
  pending. Isolated compatibility evidence does not satisfy this acceptance gate.

## Learning judgment

No durable learning beyond the source, regression tests and installation guide.
