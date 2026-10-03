# System, integration and release test catalog

This is the reusable acceptance catalog for the macOS Jev Codex Router. Stable
case IDs identify product risks, not individual unit tests. Keep execution
results in a separate [release test record](release-test-record-template.md);
this catalog is not a claim that the latest candidate passed.

Scope: normal ChatGPT-account Codex, explicit Jev CLI profile, optional native
Desktop Auto/Manual integration, canonical transport, policy and installation.
Windows portability remains a manually dispatched advisory lane. This catalog
does not establish Windows product support or Jev Ultra support.

## Execution and evidence rules

- Record source commit, dirty-file hashes, installed runtime hashes, app build,
  native binary version/hash, test command, time zone and run ID. A clean source
  checkout does not establish which code a running adapter loaded.
- Use `PASS`, `FAIL`, `BLOCKED`, `NOT RUN` or `SKIP` per case and evidence layer.
  Give a reason for every non-PASS. An unavailable account, binary or UI surface
  is not a pass. Preserve failed attempts and their correction evidence.
- `F` means automated isolated fixture; `N` means actual native app-server with
  loopback endpoints; `L` means live TypeSafe/OpenAI inference; `U` means native
  Desktop UI; `R` means release/installation audit. A pass at one layer never
  implies a pass at another. Browser-panel tests are not native Desktop tests.
- Use synthetic inputs for live tests. Keep keys, caller capabilities, account
  identifiers, raw transcripts, logs and private backups out of the repository.
  Publish only reviewed summaries; retain restricted evidence and its hash in
  the private run record. Never put credentials on a command line.
- Join native thread/turn/item IDs, HTTP request/response IDs, tool call IDs and
  observed message IDs. Document any ID rewriting and its mapping. A time
  window, answer prefix or model's own description is not sufficient proof.
- Distinguish the route that generated the current answer from a separate probe
  that the answer reports. A Sol answer can truthfully report a Luna probe.
  Check each against its own request and response, not against each other.
- Full tool schemas belong to the canonical execution relay. TypeSafe receives
  the bounded judgment dossier. Do not claim that TypeSafe received complete
  tools just because the execution model did.
- A reused result needs unchanged relevant source, dependencies and contract
  inputs. Document the comparison. A failed full suite plus passing affected
  rerun is not a newly green full-suite execution.
- Never restore the historical configuration backup wholesale, change the
  owner's global provider, use the running service as a failure-injection
  fixture, or automatically restart Desktop.

## Command groups

Run from the repository root unless a subshell changes directory. Node.js
22.19+ and Python 3.11+ are required. Install declared dependencies before the
checks. Record the actual versions; do not silently discover an old CLI.

### C1 — complete required local checks

```sh
python3 -m unittest discover -s server -p 'test_*.py'
python3 -m compileall -q server poc
python3 poc/eval_routing.py
(cd router && npm run check && npm test)
(cd router && npm audit --omit=dev --audit-level=high)
git diff --check
```

### C2 — Desktop fixtures and actual native protocol

Set these variables to inspected local files. The binary must be the actual
bundled executable, not a shell trampoline. The catalog must contain official
model metadata, including the supported carrier; it is a test input, not a
new global catalog setting. Before running, copy inspected official metadata
to a separate immutable snapshot and point the variable at that snapshot. Do
not point it at the app's live `models_cache.json`: background `fetched_at`
updates would violate the fixture's input-file preservation assertion. The
fixture copies the snapshot into an isolated home.

```sh
export CODEX_BIN='/absolute/path/to/verified/codex'
export JEV_DESKTOP_NATIVE_BINARY="$CODEX_BIN"
export JEV_DESKTOP_NATIVE_CATALOG='/absolute/path/to/official-models.json'
(cd router && node --test test/desktop-provider-bridge.test.mjs test/desktop-provider-state.test.mjs test/desktop-provider-native.test.mjs test/desktop-launch.test.mjs)
```

Native cases skip without their prerequisites. Inspect the output and require
those specific cases to execute for Desktop acceptance. Keep `CODEX_BIN` set
for C1 when that suite uses CLI discovery. The original native Desktop build
and the separately supported profile CLI need not be the same version.

### C3 — relay, policy and isolated profile contracts

```sh
(cd router && node --test --test-name-pattern='receives the complete canonical replay' test/routing.test.mjs)
python3 -m unittest discover -s server -p 'test_selection_mode.py'
python3 -m unittest discover -s server -p 'test_per_call_routing.py'
python3 -m unittest discover -s server -p 'test_answer_signature.py'
python3 -m unittest discover -s server -p 'test_plan_mode.py'
```

The profile test requires a separately verified CLI supporting layered
`<name>.config.toml` profiles (CI currently pins 0.159.3):

```sh
export CODEX_ISOLATION_TEST_BIN='/absolute/path/to/verified/profile-capable/codex'
(cd router && node --test test/isolated-codex-http.test.mjs)
```

### C4 — installer transactions

```sh
python3 -m unittest discover -s server -p 'test_install_*.py'
python3 -m unittest discover -s server -p 'test_runtime_paths.py'
```

The fixture commands above do not authorize a production reinstall. For an
already authorized live installation, snapshot protected-file hashes and app
process identity first, use root `./install.sh --desktop`, inspect the result,
then repeat once to evaluate idempotence. Do not invoke component installers
independently. Do not treat `--prepare-only` as live installation evidence.

## Integration cases

All cases are mandatory when their subsystem changes; release-wide selection
and evidence reuse are recorded explicitly. `L` and `U` procedures below are
additional to C1–C4, not consequences of their success.

| ID / layer | Preconditions and command or procedure | Expected result and required evidence |
| --- | --- | --- |
| INT-01 F/N | C3 profile HTTP test with two isolated endpoints; inspect default/profile TOML. | Default traffic reaches only the ordinary endpoint; explicit Jev traffic reaches only authenticated Jev. No global router base URL, provider override or custom catalog. Capture both endpoint request counts and parsed config. |
| INT-02 F | C2 `new Jev thread gets only thread-scoped provider config` and `Jev model default writes never reach native disk and keep expectedVersion validation`. | Jev definitions are per-thread; official config bytes remain unchanged; concurrency validation remains effective. |
| INT-03 F/N | C2 model-list, missing-carrier, pin and official pass-through cases. | Official entries remain intact; exactly Auto/Manual are added only with supported carrier/pins. Missing carrier disables Jev without breaking official selection. |
| INT-04 F | C3 canonical replay cases, both routes and Desktop carrier variants. | Valid mode marker restores correct Jev route after authentication; invalid marker/carrier combination is rejected; marker is consumed; unmarked official Sol remains official. Retain ingress/forwarded assertions. |
| INT-05 F | C3 `test_responses_lite_preserves_header_and_additional_tools` plus canonical replay cases. | Exact supported Responses-lite header and complete `additional_tools` reach execution; unrelated provider/auth headers do not leak. Compare canonical payload and tool definitions. |
| INT-06 F | C3 per-call tests for model swaps, cache controls, completed search, compaction and full handoff. | Canonical messages, tool calls/results and supported metadata survive. Bounded Jev projection never replaces execution context. |
| INT-07 F | C3 selection-mode suite, especially `test_manual_all_efforts_override_judge`. | Manual low/medium/high/xhigh/max preserve explicit effort even when Jev suggests another effort. Missing effort defaults medium; invalid/Ultra values are rejected before judgment. |
| INT-08 F | C3 Auto sentinel/stale-update and mode/effort lease tests. | Auto applies current judgment, not inherited UI effort. No `auto` sentinel reaches execution; changing mode/effort invalidates incompatible lease. |
| INT-09 F/N | C2 `native effort-only updates keep Jev model identity in Desktop settings notifications`. Feed the actual notification into the next request. | Nested `threadSettings.model` and collaboration settings preserve Jev alias through effort changes; underlying mode/effort remain correct; explicit official selection still works. Compare public and raw native notifications/requests. |
| INT-10 F/N | C2 provider-switch and native pressure tests; switch official → Auto → Manual → official on idle persisted thread. | Same thread/history and exact permission policy survive; effective provider is verified before acknowledgement; no hidden permission expansion. |
| INT-11 F | C2 busy/non-persisted, subscriber, missing permission provenance and failed-resume cases. | Unsafe crossing fails before sending a turn; rollback restores original verified route/permissions. Unconfirmed restoration blocks further affected turns. |
| INT-12 F/N | C2 state tests and reopen tests; restart only test-owned adapter. | Confirmed Auto/Manual route survives restart; owner-only records contain allowed fields; pending/corrupt/conflicting/stale-writer state fails closed for affected route only. Official lists and other threads remain available. |
| INT-13 F | C2 colliding callback-ID test and unknown-method/compact pass-through test. | Native callback/approval correlation and decisions survive; unknown native methods and official compaction remain unchanged. |
| INT-14 N | C2 `native pressure reproduces unknown alias compaction; known metadata preserves mode, effort, and restart`. | Reproduce unknown-model limit, then known carrier uses expected effective window for the pinned build; successive supported turns avoid spurious repeated compaction. Real compaction remains enabled. Record observed window, usage and compact events. |
| INT-15 F | C3 `test_direct_judge_receives_bounded_research_and_only_current_candidates`, invalid judgment and missing-key/error cases. | Direct TypeSafe contract contains current candidates and bounded decision data. Technical fallback uses approved Sol/high in Auto; Manual retains selected effort. No gateway/proxy or silent provider substitution. |
| INT-16 F | Selection-mode, per-call, fallback-constraint and Jev server tests in C1. | Kill switch/shadow precedence survives; quota fallback preserves compatible exact Manual effort, cannot recurse into Jev, and refuses when no compatible candidate exists. Canonical context remains intact. |
| INT-17 F | C3 Plan suite and offline routing dossier. | Trusted native mode controls adaptive planning; quoted/untrusted `plan` text does not. Bounded review guidance does not claim actual review or override permissions. Preserve Manual effort and kill/shadow/quota controls. |
| INT-18 F | C3 answer-signature suite; include stream fragmentation, terminal reconstruction, interleaved messages and replay. | One actual-route prefix per supported message, no duplication or corruption; tool arguments untouched; old headers removed on replay; displayed effort corresponds to that message's execution. |

## System acceptance cases

Live tests require authorized synthetic data and the existing direct TypeSafe
path. Save structured observations; the model being tested must not certify
its own success. For UI cases, the owner restarts Desktop if needed and selects
the model/slider; typing “test medium” does not change effort.

| ID / layer | Preconditions and procedure | Expected result and required evidence |
| --- | --- | --- |
| SYS-01 L/U | Open original app normally; fresh official Sol chat; send unique synthetic token; exercise native compaction. | Official response and compaction complete through normal account/provider; no Jev decision/request for those correlated turns. Preserve pre/post config hash and actual native completion evidence. |
| SYS-02 U | Start reviewed optional launcher; inspect picker and native effort settings. | Official models plus Auto/Manual visible; selecting each persists. Max visibility is checked separately from Max execution; official Ultra does not add Jev Ultra. Screenshot plus app/build identity. |
| SYS-03 L/U | Auto with UI High; synthetic prompt followed by tool result. | Mode=auto reaches relay and bounded TypeSafe dossier; capture actual Jev response and applied model/effort. UI effort need not match actual Auto effort. Record lease reuse separately from fresh judgments. |
| SYS-04 L/U | Manual matrix: Light(low), Medium, High, Extra High(xhigh), Max. Wait for completion before each change. | Alias remains Manual; actual upstream reasoning effort matches each selected value regardless of Jev's suggested effort. Record five turn IDs, incoming effort, decision, applied effort and response metadata. |
| SYS-05 L | Auto and Manual synthetic dynamic tool: place a random enum only in tool schema, create a second nonce only when callback executes. | Model uses schema enum; Codex dispatches exactly intended callback; final answer contains callback nonce. Compare tool-set hashes at ingress, relay receipt and execution forwarding, tool call IDs, results and final message IDs. |
| SYS-06 L | Instrument the same SYS-03/04/05 runs with metadata-only, reviewed observation at judgment and execution boundaries. | Direct TypeSafe response → normalized decision → actual forwarded model/effort → upstream response metadata → Codex message form a single joined trace. Manual override and lease reuse are explicit; absent/conflicting metadata is inconclusive or FAIL, never inferred from answer text. |
| SYS-07 L/U | Compare visible route prefix with actual response metadata for that exact answer; run a separately identified nested probe using a different candidate. | Outer answer route and nested probe result are reported separately. Join each to its own IDs. If prefix disagrees with its own execution, FAIL; if only nested probe differs, do not misclassify it as a route defect. Include a genuine non-Sol response when available; synthetic fixture alone cannot certify live non-Sol labeling. |
| SYS-08 U/N | On idle persisted chat, switch official → Auto → Manual → official; reopen via user-controlled restart. | Model identity, effort, history and permissions remain correct after switches/reconnect. UI evidence supplements INT-10/12; adapter-only replay does not prove native UI. |
| SYS-09 U/L | Several short turns in Jev chat with representative context; explicitly request supported native compaction separately. | No automatic compaction before every short turn due to wrong carrier metadata; legitimate compaction completes and subsequent mode/effort remains correct. Record actual usage/window/compact events; a short low-context turn alone does not reproduce pressure. |
| SYS-10 R/U | Validate launch with stale or changed app/native pins using isolated fixture; inspect actual installed pins. | Unsupported build uses ordinary Codex without adapter; signed original bundle stays unmodified. User restart is never automated. Do not tamper with the installed app to test this condition. |

## Release and installation cases

| ID / layer | Preconditions and procedure | Expected result and required evidence |
| --- | --- | --- |
| REL-01 F/R | C4 fresh-install/reinstall tests; authorized live root install only after review. | Default/profile TOML parse; official route is not localhost; Jev isolated; unrelated settings/auth bytes and designated protected backup unchanged. Record hashes, not contents. |
| REL-02 F/R | C4 idempotence and both-route publication tests; authorized second installation. | Same logical configuration and protected bytes; Auto/Manual registered before smoke requests; no duplicate entries or reintroduced global defaults. Record both exit statuses and before/after manifest/config hashes. |
| REL-03 F | C4 late-failure, ownership, service-stop and restore cases on synthetic homes. | Transaction snapshots before mutation, restores both profiles/state on injected failures; services stop before restore; original file modes survive. Preserve failures instead of hiding bootstrap uncertainty behind retries. |
| REL-04 F/R | C4 path/symlink/unknown-app tests; inspect runtime manifest. | Unsafe paths and unknown builds rejected before writes. External per-thread route records stay outside installer snapshot/rollback; active state revisions/locks are not copied or rewound. |
| REL-05 R | Run C1 and applicable C2–C4 on identified candidate; compare installed common-file hashes and any declared private overlay. | Required suites/checks pass or every gap is disclosed; native cases actually run. Preserve exact fail/skip totals. Full suite includes existing broader embedded-router coverage. |
| REL-06 R | One integrated acceptance/code/Python review as applicable; record verdict on final hashes and affected corrections. | No unresolved release-blocking issue; reviewers read same candidate. Test-only edits and reused unchanged evidence are explicit. |
| REL-07 R | Inspect source diff, staged content, secret checks, license/source provenance and runtime exclusions. | No credentials, raw user evidence, install backups or unrelated WIP enter release. Follow [secret checks](secret-check.md); record candidate/staged scan outcome without secret material. |
| REL-08 R | Run C1 and inspect repository Actions permission. | Required local checks pass on the candidate. The owner disabled Actions on 2026-10-02, so remote CI is not a merge gate. Retain workflow definitions and report unexecuted platform limits; disabled or billing-blocked jobs are never PASS. |
| REL-09 R/U | Complete live/UI case records after reviewed installation; retain run manifest, rollback boundary and manual launcher instructions. | No claim of release completion with unresolved mandatory UI/route/metadata issue. Record source/installed/loaded versions separately; signed app/config/backup unchanged and no automatic restart. |

## Baseline evidence and present limitations

This table is a historical starting point, not an acceptance verdict for a new
candidate. The owner holds private raw evidence; do not add private file paths
or raw records to the public repository.

| Observation | Evidence and limitation |
| --- | --- |
| Official/profile isolation | [Isolation report](provider-isolation.md) records separate fixture endpoints, official live inference/compaction and explicit profile inference. Revalidate changed contracts; old totals are not latest-candidate totals. |
| Mode policy | [Selection-mode report](selection-modes.md) documents five-effort local HTTP coverage, fallback and CLI live checks. Its earlier Desktop-pending paragraph describes that historical phase. |
| Desktop adapter | [Native integration](native-desktop-bridge.md) records carrier/context handling and nested notification correction. Native fixture success does not certify final UI acceptance. |
| Live tool roundtrip | Owner-held run `8bbf851d-8ff7-4678-b513-1b00bf1b8209` recorded two direct Jev judgments, four upstream executions, four matching tool-set boundary hashes and two callback-only nonces. Auto applied low; Manual retained medium despite Jev low. Actual response message IDs were matched with native notifications. |
| Last documented local candidate before this catalog | Commit `3486add86594b991f18a1142266347e697fe72c0`: full Node run 4472 PASS / 1 FAIL / 32 SKIP; PID fixture correction then 19 PASS / 0 FAIL / 2 SKIP for its file; alias-focused 34 PASS / 0 FAIL / 0 SKIP. Unchanged Python production reused 255 PASS. This is not a fully green repeat of the entire Node suite. |
| Latest owner UI report | Owner reports normal/Auto/Manual working, including five Manual effort screenshots. Seven saved direct-probe artifacts were re-read: official Sol/high, Auto Sol/low, Manual Luna/low and Sol/medium/high/xhigh/max all record HTTP 200, completion and returned test tokens. Relay metadata independently records matching Luna/low and Sol/low labels on different message IDs. The screenshot-to-native-item join remains unavailable; six probe artifacts omit response IDs. SYS-07 remains unverified at the UI layer, not a demonstrated wrong-label incident. |
| Label disagreement boundary | The current prefix is created from the selected route before execution. A synthetic selected-Sol / returned-Luna response retains the Sol prefix while the private observer marks metadata mismatch. This is a separate known limitation, not the demonstrated cause of the owner screenshot. INT-18/SYS-07 must retain this negative case; do not claim backend-confirmed labeling for mismatched or absent metadata. |
| Publication | Historical PR #4 CI did not start because of billing/spending-limit errors. The owner later disabled Actions and authorized merge after local checks and integrated review. Read current PR state and candidate evidence; do not infer merge or CI success. |

## Maintenance

Keep existing IDs stable. Add cases for a new failure at its actual boundary,
link the regression file and required live/UI evidence, and update the run
record rather than editing old results to PASS. Retire cases with a dated
reason instead of reusing an ID. On an app/protocol update, re-evaluate native
pins, response shape, effort menu, notification mapping and context thresholds.
Do not copy old numeric expectations onto a new build without evidence.

Related contracts: [provider isolation](provider-isolation.md),
[selection modes](selection-modes.md), [native Desktop](native-desktop-bridge.md),
[adaptive planning](adaptive-planning.md), and historical
[private preview verification](VERIFICATION.md).
