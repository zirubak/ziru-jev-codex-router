# Maintenance and release checklist

This is the Jev monorepo release contract. The embedded router's version,
changelog and upstream release artifacts are not releases of this project.

## Before publishing

- Identify the exact source commit and scoped fixes; link their issues.
- Require all applicable checks in [SUPPORT.md](SUPPORT.md) to complete
  successfully on that commit. Record skips and investigate failures rather
  than lowering assertions or silently disabling a platform.
- Review dependency/lockfile changes, licenses and audit output.
- Review context preservation, retry boundaries, privacy, and migration impact
  for any affected component.
- On macOS, separately qualify the root installer and update path using an
  isolated test profile. Record paths and rollback behavior without credentials.
- If live routing changed, perform the explicitly authorized live smoke check.
  Record policy and terminal status without prompts or credentials. Unit tests
  alone are not proof of deployed runtime health.
- Write release notes distinguishing code changes, compatibility, known limits,
  and measured results. Do not claim quota savings from a fixed-token simulation.
- Verify the remote commit equals the tested source. If publishing archives,
  build from that source and verify their contents and checksums. Claim signatures
  or provenance only when actually generated and verified.

## After publishing

- Verify the published tag/artifact resolves to the intended source.
- Link the tested commit and CI run when closing issues.
- For a deployment, read back running policy/health separately from Git status.
- Roll back with a reviewed revert or known source version, preserving user
  state. Never rewrite shared history or delete credentials as a rollback.

## Repository controls

Private vulnerability reporting belongs to this repository, not the upstream
fork. Recheck its availability before changing the reporting documentation.

Branch protections and rulesets are repository settings, not implied by this
document. Agree stable check names and merge policy before enforcing them;
read back the actual GitHub settings before claiming protection. Do not make a
new or failing platform check a required merge gate without qualification.

## Deferred until an explicitly authorized public release

Owner decision, 2026-10-01 (America/Los_Angeles): defer Star History setup until
this repository is made public. Do not request or create a token for it now.
When the owner explicitly requests public release, check Star History's current
integration/authentication requirements, configure the supported README embed,
and verify that the actual chart renders in both READMEs. Do not assume that
changing visibility alone resolves the previously observed HTTP 403. Never put
raw access tokens in README files, image URLs, commits or chat. This note is a
future release checklist item, not authorization to change repository visibility
or create credentials automatically.

## Published previews

- [v0.1.0-preview.1 notes](release/v0.1.0-preview.1.md) — first private macOS
  preview, source `cf7c6c0b2ced07aa40b8c39f777c9dec8b9a18f2`.
  [GitHub Release](https://github.com/zirubak/ziru-jev-codex-router/releases/tag/v0.1.0-preview.1).
