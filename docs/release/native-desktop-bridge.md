# Optional native Desktop integration

Status: the owner confirmed Auto/Manual switching and effort-slider behavior
in a fresh Desktop session on 2026-10-02 after the nested-notification alias
correction. This is owner-reported UI acceptance, separate from the native
protocol and actual inference evidence below.
This is an internal, build-specific integration, not an officially supported
Desktop extension API.

The optional launcher preserves the original signed application bundle and the
normal Codex config. It adds two models to the native app-server model list:

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

Jev UI aliases use the known native `gpt-6.1-sol` metadata with separate
`jev-router-auto` and `jev-router-manual` thread providers. Their explicit
`x-jev-selection-mode` header selects the existing Jev route at the authenticated
local ingress; an unmarked official Sol request is never reclassified. The
alias is restored for display only for a verified Jev route. If native model
metadata for the carrier is unavailable, Jev is unavailable rather than using
unknown-model defaults.

The pinned Desktop build reads its current model and next-turn collaboration
settings from `thread/settings/updated.params.threadSettings`. Both nested
model fields must retain the Jev alias. Restoring only the outer envelope leaks
the internal Sol name into the picker and can make a later effort change select
the official provider. The native regression feeds the public notification
back into the next turn and checks the mode, effort and read-only permissions,
including an explicit return to the official provider.

For the pinned build, Jev threads request the supported 872000 context window
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
5. Verify ordinary original-app launch still works and an updated build disables
   this integration. An app-server fixture is not native UI acceptance.

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

| Desktop build | Bundled CLI | Adapter support |
| --- | --- | --- |
| 12776 | 0.159.0-alpha.12.1 | Verified artifact hashes and native checks |
| 12947 | 0.160.0 | Reported in issue #16; unverified, installation refused |
| Other artifact hashes | Any | Unverified, installation refused |

Build numbers describe the tested environment; exact app.asar and Mach-O hashes
remain the compatibility gate. The current readback in [issue #16](https://github.com/zirubak/ziru-jev-codex-router/issues/16)
does not establish the app build at each earlier failure.

`./install.sh --desktop` checks compatibility before dependency preparation,
transaction backups, configuration writes, service starts or live smoke requests.
Installation checks again inside the transaction; if the app changes after the
first check, the existing rollback safeguards still apply. Launch and respawn
checks remain unchanged.

You can check compatibility without installing:

```sh
python3 server/install_desktop.py --check
```

If your app is unsupported, retain ordinary Desktop. For the separate CLI route,
use the root `./install.sh` without `--desktop`, then `codex -p jev`; Manual uses
`codex -p jev -m jev/manual -c model_reasoning_effort=high`. This path requires
the normal installation prerequisites and a CLI with profile-file support. A
successful installer smoke does not prove interactive CLI or Desktop execution,
or distinguish semantic Jev selection from technical fallback.

To qualify an updated app, maintainers must verify its signature, inspect native
protocol and picker changes, run the adapter regression checks, and verify actual
Auto/Manual requests, official-provider isolation, tools, permissions, history,
and native collaboration on that build. Only then should reviewed hashes be
published together with build/CLI versions and acceptance evidence. Copying new
hashes alone does not establish support. Build 12947 remains unverified here.
