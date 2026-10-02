# Maintenance and release checklist

This is the Jev monorepo release contract. The embedded router's version,
changelog and upstream release artifacts are not releases of this project.

## Before publishing

- Identify the exact source commit and scoped fixes; link their issues.
- Require the five macOS product CI jobs listed in
  [SUPPORT.md](SUPPORT.md) to complete successfully on that commit. Record
  skips and investigate failures rather than lowering assertions or silently
  disabling a platform. Windows runs separately as advisory portability
  feedback; its pending, failed or cancelled result does not gate this release.
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
The required job names are `Jev server (ubuntu-latest, Python 3.11)`,
`Jev server (macos-latest, Python 3.12)`, `Embedded router (ubuntu-latest)`,
`Embedded router (macos-latest)` and
`Codex app-server contract (0.155.0-alpha.9.2)`. Exclude
`Embedded router (windows-latest, advisory)` and the former
`Embedded router (windows-latest)` from required checks.

On 2026-10-02, the protection and ruleset API reads returned HTTP 403 with
`Upgrade to GitHub Pro or make this repository public to enable this feature.`
No branch protection or ruleset update is claimed. The workflow split and
documented owner merge policy apply independently of those unavailable settings.

## Actions usage controls (2026-10-02)

- Windows portability feedback is manual-only; keep its full assertions and
  visible failure results without launching it on every PR or `main` push.
- Both workflows cancel superseded runs for the same PR/ref.
- Keep the five product jobs and their test commands; do not bypass required
  checks to compensate for an account billing restriction.
- CI run `37048612646` and advisory run `37048612592` did not start tests.
  GitHub reported: `The job was not started because recent account payments
  have failed or your spending limit needs to be increased. Please check the
  'Billing & plans' section in your settings`. This message does not distinguish
  failed payments from a spending limit; no actual charges are asserted.
- Account budgets, payment methods and spending limits are separate from
  repository workflows. No paid usage increase or account billing change is
  authorized or claimed by this policy change.

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
