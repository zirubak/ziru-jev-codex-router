# Issue #5: official Ultra settings candidate

Status: local fix and tests complete; review, product acceptance and merge blocked.
This candidate is based on unmerged PR #4 at
`f2217b5d76e00be2e74cd887b99a9b560f552547`. It must not be presented as a
verified default-branch release or an installed fix.

Official private route efforts now follow the bundled native client's non-empty
string contract, including Ultra; Jev Auto/Manual retain their existing bounded
low-through-max contract. Proposed route metadata is validated before storage
and native mutation. Invalid proposed metadata leaves the last confirmed route
usable for a valid retry. Storage, revision and corrupted-state failures retain
fail-closed behavior. Serialized route records remain bounded to 4096 bytes.
No Ultra value is mapped into Jev's raw backend HTTP routing.

RED reproduced the storage rejection using the actual bundled CLI, real private
state and local HTTP carrier. GREEN covers official Max to Ultra after Jev,
Jev to official Ultra, exact native notifications, reopening, valid retry after
pre-RPC rejection, unchanged Jev effort bounds and storage failure blocking.

## Verification

- Bundled CLI: `codex-cli 0.159.0-alpha.12.1`; generated app-server schema defines
  ReasoningEffort as a string with minLength 1.
- Focused Desktop tests with explicit native binary/catalog: 40 passed, no skips.
- Full Node suite: 4511 tests, 4474 passed, 37 conditional skips, zero failures.
  The explicit focused run covers all three native tests skipped by default.
  Other platform/external-runtime conditional skips remain unverified.
- Python: 255 passed. Existing ResourceWarning output is not a test failure.
- Python byte compilation, offline routing dossier, npm syntax checks and
  production dependency audit passed; no production dependency vulnerabilities.
- Changed module coverage: lines 97.64%, branches 83.85%, functions 100%.
- Candidate source/test hashes and machine-readable results:
  [verification manifest](issue-5-official-ultra-2026-10-02.json).

Run the native regression without using the owner's running service:

```sh
JEV_DESKTOP_NATIVE_BINARY=/path/to/bundled/codex \
JEV_DESKTOP_NATIVE_CATALOG=/path/to/native-models.json \
node --test router/test/desktop-provider-bridge.test.mjs \
  router/test/desktop-provider-state.test.mjs \
  router/test/desktop-provider-native.test.mjs
```

## Unmet gates

Code and Python reviewer agents each failed to start with HTTP 502 from the
local router, including retry. No independent review or approval was obtained.
GitHub reported: recent account payments failed or spending limit must increase;
required CI jobs did not start. Do not waive or bypass those checks.
Native Desktop UI selection and authenticated Ultra/delegation execution have
not been verified. Native RPC settings acceptance alone does not prove either.
No installation, original app bundle, live thread, service or global settings
were modified. PR #4 is a prerequisite before this patch can reach main.

No durable learning beyond source, tests and existing operating contracts.
