# Explicit Jev provider isolation

The former installer wrote `openai_base_url` and `model_catalog_json` at the
root of Codex's user configuration. That redirected official models and remote
compaction through the local router. Catalog entries also do not switch
providers: `jev/auto` could retain the built-in OpenAI provider and fail the
ChatGPT model allowlist.

The installer now creates `$CODEX_HOME/jev.config.toml`. Selecting `codex -p jev`
loads the custom model, the `jev-router` provider and the router catalog
together. This profile's provider alone uses `127.0.0.1:4202/v1`. Its protected
caller-key command authenticates the local request; `requires_openai_auth=false`
keeps the client's ChatGPT authentication out of that transport. Native sharing
remains a separate router-owned operation.

The default `config.toml` remains client-owned. Recognized legacy router
blocks can be removed without restoring an old backup or replacing unrelated
tables. Unowned profile conflicts, routed defaults, and global router URLs
(including provider-table endpoints) abort installation. The persistent
`isolated-codex.json` policy prevents repair and refresh commands from entering
the old global provider/default writer. Shared-service ownership and doctor
recognize the explicit profile. Failed root installation restores both
configuration files; embedded repair retains an existing profile.

Use a client whose help describes `-p` as layering `<name>.config.toml`.
The local profile contract was verified with Desktop
`0.159.0-alpha.12.1` and CLI `0.159.3`; CI pins the latter. The previous
`0.155.0-alpha.9.2` legacy app-server contract remains a separate lane.

## Verification

- Parse the default and profile TOML and validate default/provider isolation.
- Install twice on synthetic homes: default and profile remain byte-identical.
- Inject late installer failures: restore existing profiles, remove new profiles,
  and preserve unrelated settings and authentication state.
- Inject an embedded service-install failure: preserve the existing profile.
- Run the real CLI against two local HTTP fixtures: default requests reach only
  the ordinary endpoint, explicit Jev requests reach only the authenticated
  router endpoint.
- Confirm the installed stack's smoke request completes, then verify a fresh
  official ChatGPT turn, official remote compaction, and an explicit Jev turn.

Local live checks on 2026-10-02 completed successfully. The official provider
returned the expected test text and a completed context compaction. The Jev
profile returned the expected test text; its stack smoke returned HTTP 200 and
`completed`. The default configuration hash was unchanged by the full install.
The final local Node suite reported 4,455 tests, 4,424 passes, zero failures,
and 31 platform/live skips; the additional embedded rollback fixture passed.
The Python suite passed 210 tests. Syntax, the offline routing dossier, and
the dependency audit passed. Two read-only integrated specialist reviews
approved the final production candidate.

Synthetic endpoint tests establish transport selection independently of live
account availability; they do not by themselves prove provider inference.

## Manual check

1. Open a fresh normal Codex chat, select an official model, and send a short
   prompt. Use a fresh chat if an older one saved `jev/auto` with OpenAI.
2. In Terminal, run `codex -p jev` and send a short prompt. Verify a new router
   decision-log entry and the displayed route when labels are enabled.
3. Return to normal Codex without `-p jev`. The ordinary picker should contain
   official models, and `config.toml` should have no router URL/catalog override.

Never restore the former configuration backup wholesale. Do not edit or remove
the original backup; preserve safe preferences by merging individual settings.
No automatic Codex or ChatGPT app restart is part of the installation.
