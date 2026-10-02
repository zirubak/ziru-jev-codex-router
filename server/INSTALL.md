# Operations runbook

`jev_server.py` listens on `127.0.0.1:4319` and receives Responses requests for
the `jev/auto` model from the router fork embedded at `../router`. For each turn it asks Jev for a route
(tier + thinking depth), applies the routing policy, and relays the request to
the Codex Router's local caller edge, which serves native GPT models from the
shared ChatGPT session.

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
| Hide the model | `router/bin/control picker set jev/auto hide` |
| Disable the provider | `bin/jev-codex-router router providers generic disable jev` |
| Revoke native sharing | `bin/jev-codex-router router chatgpt-session disable` |

## After an embedded router update

`bin/jev-codex-router update` fetches this repository's `origin/main`, updates
the complete monorepo and invokes the root installer. It never pulls the
embedded router from a second checkout. Provider and model state live outside
the source tree, so updates should not touch them. Verify anyway:

1. `bin/jev-codex-router router providers generic list` → should show `SHOW jev`.
2. `cat ~/.codex/codex-router/model-picker.json` → `jev/auto` under `visible`.
3. `curl -s http://127.0.0.1:4319/health` → `{"ok": true...}`.
4. If needed: `bin/jev-codex-router router refresh-catalog`, then start `codex -p jev`.

## Troubleshooting

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
Install rollback restores both configuration files. Keep old backup files
untouched; restore individual safe preferences, never the former global route.

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

```sh
bin/jev-codex-router router providers generic disable jev
router/bin/control picker set jev/auto hide
launchctl bootout "gui/$(id -u)/com.thibaultsaintjean.jev-router"
```

The last command stops only the Jev service. A retained LaunchAgent can start it
again at login. After verifying its Label and source path belong to this install,
remove that service definition (not keys, logs or backups):

```sh
rm "$HOME/Library/LaunchAgents/com.thibaultsaintjean.jev-router.plist"
```

For complete removal of this installation's Codex integration:

```sh
bin/jev-codex-router router chatgpt-session disable
bin/jev-codex-router router uninstall
```

Revoking sharing also affects any other local clients using the shared ChatGPT
session; omit that step if they still need it. The embedded uninstall preserves
other registered client integrations and keeps the shared service while they
remain. Read its reported remaining clients. Restart Codex yourself, choose a
native model and verify router-managed config is removed using `router status`.
Do not delete credentials, logs, backups or the checkout until you have confirmed
no remaining service references it. A failed installation restores its own
transaction; never restore a whole old config over subsequent user edits.
