# Operations runbook

`jev_server.py` listens on `127.0.0.1:4319` and receives Responses requests for
the `jev/auto` and `jev/manual` models from the router fork embedded at `../router`. For each turn it asks Jev for a route
(tier + thinking depth), applies the routing policy, and relays the request to
the Codex Router's local caller edge, which serves native GPT models from the
shared ChatGPT session.

## Selection modes

`codex -p jev` uses Auto. For Manual, use
`codex -p jev -m jev/manual -c model_reasoning_effort=high`.
Auto advertises one Auto selection sentinel, which never reaches execution.
Manual accepts low/medium/high/xhigh/max and preserves exact effort across
cache, retries, Plan advice and fallback. Invalid values fail before inference;
missing effort defaults to medium. Ultra and native Desktop menu acceptance
remain outside verified support.

The optional [native Desktop candidate](../docs/release/native-desktop-bridge.md)
uses standard effort enums for both entries without patching frontend assets.
Auto ignores this client selection. Its UI gate remains pending.

## Local authentication

After registering `jev`, run from the repository root:

```sh
node server/configure-auth.mjs
```

This uses the embedded router's credential transaction, retains an existing credential,
and prints metadata only. The Jev server reads the protected `jev.key` in the
router's `generic-provider-credentials` directory. All POSTs require a Bearer
header; the parent adds it automatically. Direct `/ask` clients must add it.
No OpenAI Platform API key is needed for this local ChatGPT-session relay.
The Jev key loader checks `JEV_ENV_FILE` first when configured, then
`~/.hermes/.env`, `~/.jev.env`, and finally `TYPESAFE_API_KEY` from the process
environment.

## Lifecycle

| Action | Command |
|---|---|
| Decision log | `tail -f ~/.codex/codex-router/jev-router-live.jsonl` |
| Current-policy cost/cache report | `python3 server/report_routing.py --days 7 --policy current` |
| Kill switch (no Jev → frontier) | `touch ~/.codex/codex-router/jev-router.off` / `rm` to re-enable |
| Install the launchd service | `bash server/install-service.sh` (in your own Terminal) |
| Service status | `launchctl print gui/$(id -u)/com.thibaultsaintjean.jev-router` |
| Service restart | `launchctl kickstart -k gui/$(id -u)/com.thibaultsaintjean.jev-router` |
| Answer prefix | Create `~/.codex/codex-router/jev-router.signature` to show `[model-id / effort]` before the first text of each assistant message; remove it to disable. The label reflects the served route, including fallback. It appears with the first text delta, not before upstream reasoning begins. Structured JSON output is excluded. |
| Watchdog (no launchd) | `server/watchdog.sh`, e.g. cron every 5 min |
| Router status | `bin/jev-codex-router router status` |
| Update the monorepo | `bin/jev-codex-router update` |
| Hide the model | `router/bin/control picker set jev/auto hide
router/bin/control picker set jev/manual hide` |
| Disable the provider | `bin/jev-codex-router router providers generic disable jev` |
| Revoke native sharing | `bin/jev-codex-router router chatgpt-session disable` |

## After an embedded router update

`bin/jev-codex-router update` fetches this repository's `origin/main`, updates
the complete monorepo and invokes the root installer. It never pulls the
embedded router from a second checkout. Provider and model state live outside
the source tree, so updates should not touch them. Verify anyway:

1. `bin/jev-codex-router router providers generic list` → should show `SHOW jev`.
2. `cat ~/.codex/codex-router/model-picker.json` → `jev/auto` and `jev/manual` under `visible`.
3. `curl -s http://127.0.0.1:4319/health` → `{"ok": true...}`.
4. If needed: `bin/jev-codex-router router refresh-catalog`, then start `codex -p jev`.

## Troubleshooting

- **Responses-lite quota error after an account usage reset**: current versions
  send each lite request to the selected native model once, even if an automatic
  quota state has a future deadline. A successful native response clears that
  state; a fresh quota refusal remains an explicit 503 because external adapters
  cannot preserve the lite replay contract. The manual `jev-router.codex-dry`
  marker still blocks native execution. Restarting an older service alone does
  not invalidate its persisted automatic state. See the
  [quota boundary](../docs/release/native-desktop-bridge.md#responses-lite-quota-boundary-2026-10-02).

- **Desktop compatibility or recovery error**: `--desktop` tests the signed app
  and real bundled engine before installation side effects. Changed app artifacts
  are automatically requalified at bridge startup; no manual hash allowlist is
  required. A failed contract leaves saved Jev chats readable and rejects Jev
  inference with `jev_desktop_recovery_required`. Run the root
  `./install.sh --desktop` transaction, then quit and reopen Desktop yourself
  using the generated launcher. A foreign `CODEX_CLI_PATH` is preserved and
  reported as a conflict. See [update qualification and recovery](../docs/release/native-desktop-bridge.md#compatibility-and-app-updates).

- **`invalid_responses_response` in router logs / “unavailable right now” in
  Codex**: the API forwarder parsed our reply as JSON instead of SSE. The server
  forces `Content-Type: text/event-stream` on streamed replies for exactly this
  reason; make sure you run the current `jev_server.py`.
- **401 / route refused by the edge**: the shared ChatGPT session expired —
  re-run `bin/jev-codex-router router chatgpt-session enable`.
- **Every turn uses the technical fallback**: check the decision log (`gate` field) — the
  kill switch may be on, or the TypeSafe key is unreadable (look for
  `jev_error` / `no_key_or_task` gates). Jev errors or missing key/task
  use `gpt-6.1-sol` with `high` effort and standard speed.
- **Jev missing in its profile**: verify `jev.config.toml`, refresh the catalog,
  and invoke `codex -p jev`; the normal picker remains official.

### Model visible but rejected by ChatGPT

A model catalog entry does not select its provider. A historical thread using
`jev/auto` with `openai` can fail the ChatGPT model allowlist even when a local
router is running. A global OpenAI endpoint override also redirects official
requests, including remote compaction, through the local service.

This fork installs Jev as an explicit profile:

```sh
codex -p jev
```

`$CODEX_HOME/config.toml` remains the normal configuration. The dedicated
`$CODEX_HOME/jev.config.toml` selects `jev-router`, `jev/auto`, and the router
catalog. Only that provider points to `127.0.0.1:4202/v1`; it authenticates using
`caller-key-auth-command.mjs` reading the protected caller-secret file.
`requires_openai_auth = false` prevents the client from applying ChatGPT model
restrictions or forwarding its account credentials to this custom provider.
Native session sharing remains inside the router.

Installer and subsequent config repair/refresh commands honor the persistent
`isolated-codex.json` policy. Global signed/login-free/default-model switches
are refused. A user-owned `jev.config.toml` is never silently overwritten.
Install rollback reverses verified installer-owned changes in `config.toml`
while preserving unrelated concurrent edits, and restores the dedicated
`jev.config.toml` profile. If current configuration overlaps that ownership or
cannot be safely reconciled, rollback reports a configuration conflict. When
the current file is safely readable, it is retained privately as
`config-current.toml` in the transaction backup; otherwise the result records
that the snapshot is unavailable. Independent profile, state and service
restoration still proceeds. A conflict never reports successful configuration
restoration. Inspect the preserved
current and original files before resolving that conflict. Keep old backup
files untouched; restore individual safe preferences, never the former global
route.

The transaction retains the definitions and loaded/disabled state of the current,
legacy, and explicitly configured Jev services. Service installation validates
the generated plist before stopping them, refuses an unrelated process on
port 4319, and waits for the installed launchd PID to own a healthy listener.
Existing service definitions must match verified runtime and source anchors.
Foreign definitions and embedded legacy definitions without a verified migration
contract are preserved and refused before any service is stopped. A previously
loaded disabled service is enabled for bootstrap before its disabled state is
restored. Desktop rollback removes the verified runtime leaf and preserves an
empty env table header when the manifest cannot prove who created that table.

To verify manually, start a fresh normal official-model chat and a separate
`codex -p jev` session. Confirm the normal configuration has no router URL or
router catalog, and only the explicit session adds a router decision-log row.
The installed client's `--help` documents profile-file support; older builds
without that support need a compatible client before Jev can be used.

## Design notes

- The edge emits SSE with no Content-Type; we always re-emit
  `text/event-stream; charset=utf-8` on stream relays.
- `stream: true` is forced upstream (the edge requires it); non-stream callers
  get the final response object assembled from the SSE stream.
- One compact Jev decision starts each semantic phase. Its explicit lease can
  cover a clean same-tool chain or the clean continuations of one user turn;
  changed tools, errors, compactions and new user turns are re-classified. The
  canonical request and `prompt_cache_key` remain unchanged for every selected
  model.

## Removal

To stop using Jev while keeping the shared router and other providers:

If Desktop integration was installed, first remove its owned GUI override and
login registration. Use the installer-reported manifest path if it differs:

```sh
python3 server/desktop_session.py deactivate "$HOME/.codex/codex-router/desktop/manifest.json"
```

Then stop the Jev routes and service:

```sh
bin/jev-codex-router router providers generic disable jev
router/bin/control picker set jev/auto hide
router/bin/control picker set jev/manual hide
launchctl bootout "gui/$(id -u)/com.thibaultsaintjean.jev-router"
```

The last command stops only the Jev service. A retained LaunchAgent can start it
again at login. After verifying its Label and source path belong to this install,
remove that service definition (not keys, logs or backups):

```sh
rm "$HOME/Library/LaunchAgents/com.thibaultsaintjean.jev-router.plist"
```

For complete removal of this installation's Codex integration:

For a Desktop installation, run the `desktop_session.py deactivate` command
above before uninstalling or removing its source checkout. Quit and reopen
Desktop yourself when ready; the running app retains its existing child process.

```sh
bin/jev-codex-router router chatgpt-session disable
bin/jev-codex-router router uninstall
```

Named Desktop recovery providers and saved chat history are retained. Those
definitions keep old chats loadable; they do not select Jev as a default. They
cannot run Jev requests after its service is removed.

Revoking sharing also affects any other local clients using the shared ChatGPT
session; omit that step if they still need it. The embedded uninstall preserves
other registered client integrations and keeps the shared service while they
remain. Read its reported remaining clients. Restart Codex yourself, choose a
native model and verify router-managed config is removed using `router status`.
Do not delete credentials, logs, backups or the checkout until you have confirmed
no remaining service references it. A failed installation restores its own
transaction; never restore a whole old config over subsequent user edits.
