# Optional native Desktop integration

Status: implementation candidate. Native picker acceptance on the signed-in
account remains unverified. This is an internal, build-specific integration,
not an officially supported Desktop extension API.

The optional launcher preserves the original signed application bundle and the
normal Codex config. It adds two models to the native app-server model list:

| Model | Meaning of the existing effort selector |
| --- | --- |
| Jev Codex Router Auto | Ignored: Jev chooses both model and effort |
| Jev Codex Router Manual | Applied: Jev chooses the model and preserves the selected effort |

No frontend assets are patched. The ordinary effort menu remains unchanged.
The app may hide Max according to its existing effort settings. Some account
configurations also filter the model list through an official-model allowlist;
those configurations can hide both Jev entries. Do not restore a global custom
catalog or change feature flags to bypass that boundary.

## Installation and launch

The root transaction prepares the optional launcher with `./install.sh --desktop`.
It does not launch, stop or restart Desktop. The generated private file is
`$CODEX_ROUTER_STATE_DIR/desktop/Jev Codex.command`, normally under
`~/.codex/codex-router/desktop/`. Keep the installed source checkout available.

After saving work, quit Desktop yourself and open that launcher. An already
running app is refused rather than terminated. Opening the original application
normally uses the original Codex connection without this integration.

The launcher verifies the original app signature and pins both app.asar and the
actual bundled Mach-O executable. A changed app/native build opens ordinary
Codex without the adapter until that build has been reviewed and tested. The
current gate covers Desktop build 12776 and bundled CLI 0.159.0-alpha.12.1.
Neither installation nor launch writes shell startup files or launchctl globals.

## Provider isolation

Only Jev-selected threads receive the loopback provider definition. Official
models continue with the native provider. Jev selections are kept out of global
model defaults. Native account operations, unknown methods, approvals, tool
callbacks and compaction RPCs pass to the original app-server.

An idle, persisted thread can switch providers by resuming the same thread ID.
The adapter checks the effective model/provider and permission policy before
acknowledging the switch. Busy threads, missing history, ambiguous permission
provenance or unconfirmed switching fail explicitly before any turn is sent.
A failed switch restores the original route; an unconfirmed restoration blocks
subsequent turns until the chat is reopened. These checks do not authorize more
permissions or discard existing history.

## Acceptance checks

1. Confirm both Jev entries are visible in the native picker. If absent, retain
   ordinary Codex and report that visibility gate; do not change global routing.
2. In new chats, verify official Sol, Auto and Manual requests. Compare the actual
   routed effort with the mode contract above, not just the composer label.
3. Verify an idle persisted chat can switch back to official Sol with its
   permissions and history intact; verify official compaction separately.
4. Verify ordinary original-app launch still works and an updated build disables
   this integration. An app-server fixture is not native UI acceptance.

The isolated tests cover native provider switching, reopening saved threads,
permission preservation, rollback, callback IDs, config isolation and installer
idempotence. They do not replace signed-in native UI/inference/compaction checks.
