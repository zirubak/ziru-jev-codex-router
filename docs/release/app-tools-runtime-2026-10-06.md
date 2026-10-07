# Trusted Desktop app tool runtime

Status: complete. Local checks, integrated review, root installation and the
post-install fresh-chat tool gate passed on 2026-10-06.

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
- Implementation commit: `564665581aa4617790f9587d263cc36f4e358e8c`; local
  main fast-forward was verified. No remote push was performed.
- The owner supplied the post-install fresh-chat result. Reading that chat with
  `codex_app.read_thread` confirmed a completed `codex_app.list_threads` call
  with `limit=20`, a completed turn and no error.
- Direct `list_threads` and `read_thread` calls also succeeded in the verification
  chat. The list contained five pinned chats and twenty recent chats.
- Only the bounded result is recorded here; private chat contents and the
  full sidebar inventory are not included.

## Learning judgment

No durable learning beyond the source, regression tests and installation guide.

## Implementation file identities

- `server/install_desktop.py`: SHA-256 `e3c4aa19e69538fb0182f91c29bed5d5ef5ec6c58a0f1240459992b6a5122ccd`.
- `server/test_install_desktop.py`: SHA-256 `d4751952e7fa13a19cb92ccb4add5136a4429acf1722f358bd1849d602f1b189`.
- `server/test_desktop_app_tools.py`: SHA-256 `9594f51a557a4d873cfee3e022706d57a49b4c18da80ca874a0792dd0900a8a5`.
