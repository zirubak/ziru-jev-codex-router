# Support and test matrix

Last reviewed: 2026-10-02.

## Product support

The complete Jev Codex Router stack is supported on macOS with the current
Codex desktop application, Node.js 22.19 or newer, and Python 3.11 or newer.
The installer and background-service contract are macOS-specific because they
install launchd services and publish the model into the local Codex desktop
configuration.

Jev now uses an explicit `codex -p jev` profile instead of the normal Desktop
picker. Official Codex traffic and its catalog remain direct. Profile support
was verified with Desktop `0.159.0-alpha.12.1` and CLI `0.159.3`; see
[provider isolation](release/provider-isolation.md).

The embedded router under `router/` remains a cross-platform fork. Its portable
runtime and state-management suite runs on Ubuntu, macOS, and Windows with
Node.js 24 in the retained CI definitions. Repository Actions are disabled by
the owner as of 2026-10-02; required merge checks run locally per
[AGENTS.md](../AGENTS.md). Passing local checks does not establish results on
unexecuted platforms or make the root
launchd installer supported on Linux or Windows.

## Retained CI lanes (Actions disabled)

| Lane | Runtime | What it proves |
| --- | --- | --- |
| Jev server | Ubuntu / Python 3.11 | Minimum supported Python and portable policy/relay behavior |
| Jev server | macOS / Python 3.12 | Primary product OS and a current Python runtime |
| Embedded router | Ubuntu, macOS / Node.js 24 | Portable fork behavior, state safety, and supported product OS branches |
| Browser panel | Ubuntu / Playwright Chromium | Browser UI tests execute instead of silently skipping for a missing browser |
| Codex app-server contract | Ubuntu / `codex-cli 0.155.0-alpha.9.2` | A real, known Codex binary completes both login-free provider configurations |
| Isolated profile contract | Ubuntu / `codex-cli 0.159.3` | Explicit Jev profile and ordinary provider use separate authenticated HTTP transports |

These definitions remain available for a future owner-authorized reactivation;
they are not current merge gates. Browser-panel coverage is defined inside the
Ubuntu embedded-router job. Disabled or billing-blocked CI is not PASS.

## Advisory Windows CI

`.github/workflows/windows-advisory.yml` runs the existing Windows router
syntax checks, full test suite and production dependency audit on explicit
manual dispatches only. It does not run automatically on PR updates or `main`
pushes. Failures remain visible; they are
not converted to success or suppressed. A pending, failed or cancelled
`Embedded router (windows-latest, advisory)` check does not block macOS product
merges or releases. Do not add it to required branch checks or rulesets.

The previous combined run `37040055140` passed the five required jobs, but its
Windows job hit a port-occupancy test timeout and was later cancelled at the
workflow time limit. The cause is unresolved; moving the lane does not fix it
or establish Windows product support.

Both definitions cancel superseded runs for the same PR/ref when enabled.
Actions are currently disabled, including manual Windows dispatch. Preserve
local checks and report the remaining platform coverage limits.

The Codex contract lane sets `CODEX_ROUTER_REQUIRE_REAL_CODEX=1`; absence of the
binary is a failure, never a skip. It also checks the exact CLI version before
running the fixture. Updating that pin is a deliberate compatibility change:
run the integration locally, review request and WebSocket behavior, then update
the workflow and this document together.

Codex 0.155 may establish two authenticated WebSocket connections after a
provider-preserving configuration rewrite. The fixture accepts that bounded
reconnect only when exactly one connection relays `response.create` and the
mock upstream receives exactly one model request.

## Optional and live coverage

Routine pull-request CI never uses TypeSafe credits, ChatGPT credentials, or
real model-provider keys. Provider compatibility and the installed launchd
stack remain explicit local/release checks:

```bash
PYTHONPATH=server python3 -m unittest discover -s server -p 'test_*.py'
(cd router && npm run check && npm test)
python3 server/smoke.py
```

For a local browser-panel run, install the locked Playwright browser once:

```bash
cd router
npx playwright install chromium
```

On Linux CI, use `npx playwright install --with-deps chromium`.

## Preview release limitations

Manual Windows installation and end-to-end use have not been validated by the
maintainer. The macOS product preview may ship with this disclosed limitation;
The Windows definition is retained as portability feedback, with Actions
currently disabled. Windows testers with repository access are invited to
report sanitized results through GitHub Issues as described in both READMEs.
