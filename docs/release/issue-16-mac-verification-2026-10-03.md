# Issue 16: Mac installation and routing verification

Verified October 3, 2026 (America/New_York). Related issue: [#16](https://github.com/zirubak/ziru-jev-codex-router/issues/16).

## Outcome

The installation at revision `31000d05ef2314f7332d60578c24e19906bdf424` passed local router diagnostics and a completed live routed request. Recent local telemetry records successful Jev decisions rather than technical fallback. Desktop compatibility qualification passed for the installed native CLI, and bridge processes were present.

**Fresh-chat Auto UI acceptance is now observed; existing-chat switching still fails.** A user-supplied screenshot shows a new chat with Jev Codex Router Auto selected and a completed greeting carrying `[gpt-6.1-sol / low]`. A second screenshot shows this older installation chat rejecting the selection with “Couldn’t update model settings” and retaining GPT-6.1 Sol. This narrows the remaining issue to existing-thread transitions in the observed case. Manual UI acceptance and backend-confirmed identity remain unverified. Keep issue 16 open for the transition failure.

## Environment

| Component | Observed value |
| --- | --- |
| macOS | 26.6.2 |
| Node.js | 23.11.0 |
| Python | 3.12.3, Miniconda |
| Desktop build | 12947, earlier local readback in this troubleshooting session |
| Qualified native CLI | codex-cli 0.160.0 |
| Installed source | `31000d05ef2314f7332d60578c24e19906bdf424` |
| Router package | 0.6.0 |
| Routing policy | split-v18-selection-modes |

The Desktop build value was not read again during the final backend check. Credentials remained in a private environment file referenced through `JEV_ENV_FILE`; no credential values are included here.

## Installation history

1. Initial revision `be2a75409ce3af02c5072958dbbd66958c5886ea` failed before Jev registration because embedded doctor rejected the intermediate empty provider selection. Automatic restoration was verified byte-for-byte at that attempt.
2. Preview.2, revision `fa62e64680b2db1b4803d6274e40726be8faa00f`, fixed provider registration order. Six existing skill directories required documented external approval. Their contents matched the bundled copies apart from old management markers; existing contents were preserved.
3. Some attempts reported a Jev readiness failure. Python import succeeded and launchd was observed running the server. The cause of those earlier readiness failures was not established; no timing patch was applied.
4. A later preview.2 desktop attempt passed service health and live smoke, then rejected the unsupported Desktop build and reported rollback. CLI-only installation subsequently succeeded.
5. After selecting revision `31000d05ef2314f7332d60578c24e19906bdf424`, the root `./install.sh --desktop` transaction reported compatibility verified, Jev service OK, a completed HTTP 200 smoke request, valid catalog and isolation, desktop integration registration, and final installation success. No restoration failure was reported on this successful attempt.
6. The user then reported a model-settings toast for Auto and Manual. Restarting through the generated launcher and testing a fresh chat were recommended. Subsequent screenshots confirm a successful fresh-chat Auto selection and response, while the older chat still fails.

## Final local checks

| Check | Result and limit |
| --- | --- |
| Documented router status | Isolated configuration valid; profile present; managed service loaded and running; health OK; no degraded components |
| Documented router doctor | Completed successfully; no FAIL rows; provider credential, config privacy, isolation, background service, health, and skill-pack checks OK |
| Documented smoke | HTTP 200, terminal status `completed`, reported model `gpt-6.1-sol` |
| Recent routing telemetry | Two recent records reported `decision_source: jev`, `gate: apply`, model `gpt-6.1-sol`, effort `low`, status 200 |
| Desktop qualification | `qualified: true`, native version `codex-cli 0.160.0` |
| Bridge processes | Processes associated with the desktop bridge were present |
| Desktop model menu | Auto and Manual were visible according to the user's report; selecting either previously produced an error |
| Desktop inference | Fresh-chat Auto selection and completed response observed in a screenshot; existing-chat transition fails; Manual not yet verified |

The two telemetry records were inspected after the smoke check but were not independently correlated to screenshot items or particular UI requests. They establish recent successful Jev decision activity, not that every request used semantic routing. The smoke's model field and selected route are not independent proof of backend execution identity. Process presence is not proof of successful UI state transitions.

The cached desktop qualification listed checks covering carrier metadata, initialization/model listing, Manual efforts, Auto routing, nested settings, canonical input/tools, collaboration mode, read-only permissions, recovery, restart/resume, official-provider restoration, and context pressure. These are recorded qualification results; this verification did not rerun their entire test suite.

## Remaining acceptance steps

1. Save work, fully quit Desktop, and open the generated `Jev Codex.command` launcher.
2. In a fresh chat, select Auto and confirm the settings change succeeds; send a harmless synthetic request and confirm completion.
3. In a separate fresh chat, select Manual with High effort and repeat.
4. Select an ordinary native model and verify a response through its intended official provider.
5. If selection still fails, collect sanitized adapter/app diagnostics and report them on issue 16. Do not bypass qualification or modify the signed app bundle.

Route-label activation was instructed but not independently verified in the final backend checks. No claim of token savings, reduced subscription fees, general platform support, or completed UI acceptance is made. This report contains no keys, caller capabilities, raw conversations, private runtime logs, or installation backups.

## Suggested investigation and fix

The adapter already implements existing-provider transitions in `DesktopProviderBridge.rebind()` in `router/src/desktop-provider-bridge.mjs`. It requires an idle persisted thread, an effective permission-profile ID, exclusive unload, successful resume under the new provider, and exact preservation of permission-related metadata. New thread creation does not exercise that same transition. The screenshots alone do not identify which guard or native request failed.

First expose a sanitized specific rebind reason in the UI or local diagnostics, preserving the native error code and failing stage without prompts, credentials, or configuration contents. Reproduce with an idle thread created before adapter installation, including the permission-profile variants used by this chat and multiple native subscribers.

If the failure is a missing legacy permission-profile ID, support migration only when the native API provides a verified equivalent effective permission configuration, and compare its readback before confirming the new route. If another subscriber prevents exclusive unload, coordinate a supported unload/resume with the app rather than claiming the switch succeeded. Preserve the prior route on every failure. Do not remove idle, permission-preservation, exclusive-unload, or verification guards.

Add native contract regression coverage for official-to-Auto, official-to-Manual, and return-to-official transitions on legacy threads. Verify history, working directory, permissions, approval policy, and subscriber behavior. If safe migration is unsupported, show an actionable explanation directing the user to a new chat rather than a generic toast. This is a proposed fix direction, not an implemented or tested runtime correction.
