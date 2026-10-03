# Issue #5: official Ultra settings candidate

Status: local checks and integrated review passed; corrected source installed.
The owner authorized merge after local verification with repository Actions
disabled. Desktop restart and existing-chat UI acceptance remain unverified.
The original fix `77afbb2` is integrated with main `631f985`, preserving its
Ultra model label and owner merge policy. PR #4 supplies the provider integration.

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
- Final integrated Node suite: 4511 tests, 4480 passed, 31 conditional skips,
  zero failures. The explicit native binary and fixed official catalog execute
  the native regressions and signed-out app-server contract in this run.
  Other platform/external-runtime conditional skips remain unverified.
- Final integrated Python: 256 passed. The separate private runtime passed
  262 tests. Existing ResourceWarning output is not a test failure.
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

## Review, installation and remaining observation

The original reviewers failed to start with HTTP 502. A later integrated code
and Python review approved the original correction, then approved its current
main integration. No review-blocking finding remains. Four pre-existing unused
Python imports remain outside this patch; required syntax and unit checks pass.

An initial integrated Node run had four absent catalog-input failures and one
incorrect literal CLI-version expectation. The owner retained that failure
evidence, fixed the inputs using an immutable private official catalog snapshot
and the full `codex-cli 0.159.0-alpha.12.1` string, then reran the complete suite.
No test assertion or production behavior was disabled.

Repository Actions permission reads `enabled=false`. Historical billing-blocked
jobs remain unstarted, not PASS. Local checks and review are the authorized
merge gates. No branch protection/ruleset modification is claimed.

Root `install.sh --desktop` completed with exit 0 and an actual HTTP 200 /
completed smoke response. Five corrected source/test hashes match this record.
Normal/Jev configs, Desktop manifest, signed application assets and the affected
confirmed route remained unchanged. Unrelated runtime WIP was preserved.
Native Desktop UI selection and authenticated Ultra/delegation execution have
not been verified. Native RPC settings acceptance alone does not prove either.
The running application was not restarted and still has its earlier bridge
loaded. The user must quit and reopen the optional Jev launcher to load the fix;
existing-chat selection/send success is a separate pending observation.

No durable learning beyond source, tests and existing operating contracts.
