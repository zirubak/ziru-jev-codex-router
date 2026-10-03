# Optional native Desktop integration

Status: the owner confirmed Auto/Manual switching and effort-slider behavior
in a fresh Desktop session on 2026-10-02 after the nested-notification alias
correction. This is owner-reported UI acceptance, separate from the native
protocol and actual inference evidence below.
This is an internal, contract-checked integration, not an officially supported
Desktop extension API.

The optional launcher preserves the original signed application bundle and the
native model defaults. It adds two models to the native app-server model list:

| Model | Meaning of the existing effort selector |
| --- | --- |
| Jev Codex Router Auto | Ignored: Jev chooses both model and effort |
| Jev Codex Router Manual | Applied: Jev chooses the model and preserves the selected effort |

No frontend assets are patched. The ordinary effort menu remains unchanged.
Enable Max in Settings → Configuration → Codex → Model features → Available
reasoning efforts when that native setting is available. Checking it alone is
not evidence that a Max request executed. Official Astra Ultra does not imply
that Jev supports Ultra. Some account
configurations also filter the model list through an official-model allowlist;
those configurations can hide both Jev entries. Do not restore a global custom
catalog or change feature flags to bypass that boundary.

## Installation and launch

The root transaction prepares the optional launcher with `./install.sh --desktop`.
It does not launch, stop or restart Desktop. The generated private file is
`$CODEX_ROUTER_STATE_DIR/desktop/Jev Codex.command`, normally under
`~/.codex/codex-router/desktop/`. Keep the installed source checkout available.

After saving work, quit Desktop yourself and open that launcher once. An already
running app is refused rather than terminated. Installation registers an
owner-only wrapper in the current user's GUI `CODEX_CLI_PATH` environment and a
RunAtLoad LaunchAgent that restores it at login. The ordinary app icon and the
updater's NSWorkspace relaunch can then select the same wrapper. The wrapper
supplies its own manifest path and absolute Node executable; shell startup files
and the signed app bundle remain unchanged. A foreign environment value or
LaunchAgent is a conflict and is preserved.

The adapter qualifies the observed OpenAI-signed app and bundled native engine
against an isolated protocol and local HTTP test before enabling Jev. A new
artifact pair triggers qualification automatically, without editing a release
allowlist. Private receipts are bound to both artifact hashes, the adapter and
probe source digest, contract version, and Node version. Artifacts are checked
again after the probe so an update during qualification cannot receive a stale
success receipt. Failed qualification leaves native operation available with
recovery-only Jev providers; it does not send Jev inference.

Only the opted-in canonical `CODEX_HOME` and an actual stdio `app-server`
invocation use the bridge. Other homes and CLI commands keep native I/O.
LaunchAgent ordering before login items is not guaranteed; the recovery
registration below covers a launch that occurs before the environment is set.

To remove the GUI override and its login registration, without rewriting chat
history or model defaults:

```sh
python3 server/desktop_session.py deactivate "$HOME/.codex/codex-router/desktop/manifest.json"
```

Use the installer-reported state path when it differs. Reinstall with
`./install.sh --desktop` to restore the login registration. The launcher can
restore the current session's environment but does not reinstall the LaunchAgent.

## Provider isolation

The base config contains named recovery definitions for `jev-router-auto` and
`jev-router-manual`. They preserve access to saved Jev threads even if the
adapter is absent after an update. They do not change the selected model,
default provider, official provider table, or global model catalog. Their
recovery marker makes authenticated inference and compaction return HTTP 400
`jev_desktop_recovery_required` before any upstream request. The native engine
may repeat requests during context recovery; every attempt remains blocked. Active bridged
threads receive a scoped provider definition with `bridge-active` explicitly
overriding `required`, because native config deep-merges provider header maps.
The authenticated router consumes this marker locally; it is not an authentication
credential and is not forwarded upstream. Official models continue with the
native provider. Native account operations, unknown methods, approvals, tool
callbacks and compaction RPCs pass to the original app-server.

Jev UI aliases use the known native `gpt-6.1-sol` metadata with separate
`jev-router-auto` and `jev-router-manual` thread providers. Their explicit
`x-jev-selection-mode` header selects the existing Jev route at the authenticated
local ingress; an unmarked official Sol request is never reclassified. The
alias is restored for display only for a verified Jev route. If native model
metadata for the carrier is unavailable, Jev is unavailable rather than using
unknown-model defaults.

The qualified Desktop build reads its current model and next-turn collaboration
settings from `thread/settings/updated.params.threadSettings`. Both nested
model fields must retain the Jev alias. Restoring only the outer envelope leaks
the internal Sol name into the picker and can make a later effort change select
the official provider. The native regression feeds the public notification
back into the next turn and checks the mode, effort and read-only permissions,
including an explicit return to the official provider.

For the current contract, Jev threads request the supported 872000 context window
and 740000 compaction threshold. Unknown Jev metadata previously fell back to
an effective 258400 window, causing repeated compaction when reported input was
about 320000 tokens. This change preserves input and keeps compaction enabled.
Native Responses-lite tools remain in `additional_tools`; its protocol header
crosses the Jev relay and the existing confined API forwarder. Other providers
retain their existing transport.

Private per-thread route records contain only mode, model, effort and transaction
state. The installer points to `$CODEX_HOME/jev-desktop-thread-routes`, separate
from managed router state and installation backups. Only the adapter manages
these records, so reinstall/rollback cannot rewind a live thread's route state.
Missing, conflicting or unconfirmed route records fail closed for the affected
thread. They are not authorization to rewrite native conversation history.


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
4. After an adapter restart, verify Auto/Manual selection and the return to
   official Sol remain correct with the same thread and permissions.
5. Verify ordinary app launch and updater relaunch retain the integration after
   successful qualification. A failed qualification must keep saved Jev chats
   readable and reject Jev inference with an actionable recovery error.
   An app-server fixture is not native UI acceptance.

The isolated tests cover native provider switching, reopening saved threads,
permission preservation, rollback, callback IDs, config isolation and installer
idempotence. They do not replace signed-in native UI/inference/compaction checks.


## Responses-lite quota boundary (2026-10-02)

The native Desktop wire contract carries tools in `input[].additional_tools`.
Configured external fallback adapters have no qualified Responses-lite
transport. On known or newly observed native quota exhaustion, these calls
return HTTP 503 with an explicit contract error before external execution.
Healthy native calls preserve their complete replay. Standard Responses
profile calls retain the existing compatible quota fallback. No native tools
are silently dropped or translated into an unverified external schema.

## Compatibility and app updates

The tested host is arm64 Desktop build 12947, version 26.930.31730, with
bundled CLI 0.160.0. Build numbers are evidence labels, not permission to skip
the signature, launch-hook and behavior checks. The production probe verifies
Auto/Manual, supported efforts, nested settings, canonical input and tools,
collaboration mode, saved-thread resume, official-provider restoration,
read-only permissions and context pressure without premature compaction.

Qualification uses a private, credential-free home. On macOS, sandbox-exec
confines native network access to loopback; plugin/app discovery is disabled
only inside this fixture. Owned child process groups are terminated before
temporary files are removed. The native probe has an 18-second overall limit,
individual native requests have an 8-second limit, and signature validation
has a 5-second limit. These bounds leave room under the observed Desktop
30-second startup policy-read deadline. Filesystem stalls and future changes
to that app deadline remain outside a universal timing guarantee.

`./install.sh --desktop` checks compatibility before dependency preparation,
transaction backups, configuration writes, service starts or live smoke
requests. It checks again inside the transaction; failure restores the previous
installation. The adapter rechecks on each startup and uses a matching private
receipt to avoid repeating the native probe for unchanged inputs.

You can check compatibility without installing or using account credentials:

```sh
python3 server/install_desktop.py --check
```

A future app can remove the CLI override or change its native protocol. Such
changes cannot be guaranteed compatible in advance. They must produce an
explicit qualification failure rather than a silent model-routing change.
Saved-thread recovery and the HTTP guard are independent of GUI environment
propagation. The integration never patches signed app files, rewrites native
history, enables a global Jev default or bypasses incompatible contracts.

The observed macOS NSWorkspace relaunch behavior was tested with a disposable
app and a temporary environment marker. That test is distinct from a real
Sparkle update cycle and signed-in Desktop UI acceptance. See the
[update resilience evidence](issue-18-desktop-update-resilience.json) for the
candidate checks and remaining UI acceptance gate.
