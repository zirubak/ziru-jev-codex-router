# Jev collaboration routing — 2026-10-02

Issue: [#8](https://github.com/zirubak/ziru-jev-codex-router/issues/8).
Base: `631f985` on the public-source branch.

## Cause and behavior

The response relay inserted `jev/auto` or `jev/manual` into an omitted native
`spawn_agent.model`, including full forks. These UI route aliases are not native
model overrides. Jev children now inherit their parent's native carrier and
scoped provider. Explicit aliases matching the current Jev route become the same
inheritance request. Explicit official overrides remain unchanged. This does not
add cross-provider or Auto/Manual switching to the collaboration tool.

Jev uses a native executor, so native encrypted collaboration messages now reach
that executor without the generic external-provider plaintext relay. That extra
relay could reject the request before Jev execution. Base input normalization,
including V2 compaction triggers, remains active. External quota/cooldown
failover still normalizes handoffs for the destination. Auto and Manual preserve
canonical replay. Auth, permissions, native sharing and catalog capability
claims are unchanged.

The original payload relay HTTP 400 had no request correlation or upstream
body. Its exact historical rejection reason is not reconstructed. Isolated HTTP
RED and real native success establish the corrected routing boundary.

## Validation

- Original HTTP RED: unwanted model insertion and encrypted handoff HTTP 502.
- Integrated review caught V2 compaction and external failover regressions;
  five focused failures became green after correction.
- Final focused HTTP checks: 9 passed, including existing external handoff and
  canonical replay coverage.
- Public Python: 207 passed; compileall and offline routing dossier passed.
- Embedded syntax/schema checks passed; Node: 4424 passed, 31 skipped, 0 failed.
- Read-only code and Python specialists approved the same final source candidate.
  Code review also approved the two-file installation overlay.
- Native Desktop engine `0.159.0-alpha.12.1`: Auto/none, Manual/none, Auto/all each
  created a child, returned its unique first marker, then completed a follow-up
  on the same child with a second marker. Metadata confirmed the matching Jev
  provider; completion events confirmed at least two completed child turns.
- Ephemeral full forks lack a native rollout. The successful full-fork scenario
  used a persisted rollout in an isolated private home. Earlier fixture errors
  are not counted as successful runs.
- TypeSafe calls used its direct API. All 46 observed forwarded requests retained
  the received tool-set hash across the isolated runs.
- GitHub Actions remains disabled by owner policy; remote CI is not a pass claim.

## Installed runtime and boundaries

Live verification uses the existing reviewed Desktop bridge and selection-mode
runtime overlay, which includes work outside this main-based patch. This is not
proof that a fresh checkout of this commit contains that entire Desktop stack.
Only `router.mjs` and `namespace-relay.mjs` were updated in the installed runtime.
All other source files, Codex configs and the native app binary matched their
pre-install hashes. The root `./install.sh --desktop` transaction passed, its
smoke returned HTTP 200/completed on `gpt-6.1-sol`, and catalog/isolation validation
passed. A further native Auto child and same-child follow-up against the installed
service both completed with the matching provider. Desktop was not restarted or
UI-tested.

The fix enables collaboration execution through Jev's provider. It does not make
opaque child task text readable to TypeSafe: new isolated children can use the
existing `no_key_or_task` technical route (`gpt-6.1-sol/high` in Auto; Manual keeps
its requested effort). Full forks can be evaluated using inherited parent user
context. Do not claim child-specific semantic selection from execution success.

## Candidate SHA-256

| File | SHA-256 |
| --- | --- |
| `router/src/namespace-relay.mjs` | `e21f4bbfc15f0c91b8b56bb4a951f1ca5f2f81ae58bff294cae7a0747547a7b1` |
| `router/src/router.mjs` | `5f3c3d13c77aa739a0c25364633ad72c1783d0b444823fa1f7aa3be8f79ed14e` |
| `router/test/routing.test.mjs` | `359ec7d82bbddb65db9aa759e6a18e72d230b967b4988c9578ffa829d19f2939` |
| Installed `router/src/router.mjs` | `a002ea2dc0873b019862003735f1dc616d8b020b5658f634e438f18d3fca4366` |

The installed namespace file matches the public candidate. The installed router
retains the previous runtime overlay; the new behavior matches the reviewed
public patch, with a comment line-wrap difference.

No durable learning: the corrected boundaries are recoverable from the source,
regression tests and this release evidence.
