# Two selection modes — release evidence

## Accepted behavior

Auto retains `jev/auto` and publishes one Auto effort entry. Manual adds `jev/manual` with `low` (Light), `medium`, `high`, `xhigh`, `max`; Jev selects the model while code preserves user effort across cache, retries, Plan controls and technical fallback. Ultra remains excluded. Both routes preserve canonical replay and cannot recursively enter quota fallback.

## Candidate evidence

Catalog and canonical relay RED/GREEN were observed. Manual localhost HTTP tests cover all five levels, default/invalid effort, model names, Plan controls, mode/effort lease invalidation and quota/technical fallback. Fallback tests observed RED for recursive Manual selection, incompatible effort and ignored CLI effort, followed by GREEN. Plan advice RED confirmed a missing recommendation, then implementation preserved user effort and added bounded guidance.

The integrated candidate passed 4,466 Node tests (4,435 pass, zero failures,
31 platform/live skips) with explicitly selected Codex CLI 0.159.3. Python
passed 247 tests; syntax, offline routing dossier, dependency audit and document
checks passed. Code and Python specialists reviewed the same candidate read-only
and approved it, including the two root-installer corrections below.

Full installation initially exposed two ordering defects. The root transaction
now authorizes the existing service-ownership transfer only after its snapshot,
before writing the catalog. It also reloads the gateway after configuring both
routes, so `jev/manual` is registered before smoke tests and user calls. Executed
root-installer fixtures demonstrated both failures before the corrections.

Actual ChatGPT-account inference returned `OFFICIAL_CONTINUE_OK`. Explicit-profile
Auto returned `AUTO_FINAL_OK`; Manual returned `MANUAL_LOW_FINAL_OK` and
`MANUAL_MAX_FINAL_OK`, with matching requested/forwarded low and max effort in
sanitized attempt records. All five efforts passed localhost HTTP regression
tests; only low and max were tested against the real upstream service. These
results do not establish native Desktop menu acceptance.

The first failed installation restored configuration/profile bytes, but its
initial launchd service bootstrap failed. Explicit re-registration restored the
services; the cause of that first bootstrap failure remains unproven. No retry
loop was added to hide it. Successful final installation and repeat-install
checks are separate evidence from that failure-path limitation.

## External acceptance gates

Actual native Desktop menu rendering remains unverified: this session has no
enabled native-app control. Jev is isolated behind `codex -p jev`; the normal
Desktop picker retains official models. The accepted native menu criterion is
pending and has not been waived. The user performs any final Desktop restart.
Catalog and app-server protocol checks cannot replace visual acceptance.

GitHub runs 37049064018 and 37063332785 report that jobs did not start because
recent account payments failed or the spending limit needs to increase. Required
CI remains enabled and is not bypassed. Billing is not changed by this release.
Windows remains manual advisory. Publication may proceed as a draft; merge
requires the existing CI and product acceptance gates.

## Learning judgment

No durable learning beyond the final code, tests and existing operating contracts.
