# Adaptive planning policy

Native Codex Plan mode now carries a quality-first planning context into the
direct Jev decision request. The model and reasoning effort remain adaptive.
Substantive design considers uncertainty, interacting constraints, alternatives,
dependencies and downstream rework. Clerical edits to an accepted plan may use
a lighter model and effort. Existing mandatory Astra architecture, independent
final review and risk-review categories remain in force.

Jev also recommends a planning review level: `none`, `independent`, or
`parallel`. The recommendation is delivered as bounded developer guidance to
the executing model. Substantive plans must cover scope, non-goals, assumptions,
ordered implementation steps, dependencies, acceptance and verification.
Parallel review uses distinct bounded perspectives and consolidates findings
into one plan only when the caller's tools and authority permit delegation.
The router does not launch reviewers or certify completion of a review.

Mode detection reads a top-level native collaboration-mode envelope from
developer input messages. User text, tool output, quoted examples and fenced or
indented code do not activate it. A latest Default notice restores ordinary
routing. Root instructions without role provenance are not a mode signal.
The actual Desktop UI toggle has not been captured in this release's tests.

Plan calls bypass older route leases and receive a fresh judgment. Existing
native configuration updates are aligned with the selected effort. Each
provider retry restores original controls and adds at most one planning
guidance message. Technical Jev failure retains Sol 6.1/high and conservative
review guidance. Kill switch, shadow mode, quota fallback, authentication,
canonical context and manual Ultra boundaries remain unchanged.

## Validation

Policy version: `split-v17-adaptive-plan`.

The final candidate passed 222 server tests, including 16 focused Plan tests,
Python byte-compilation, and 16 offline routing dossiers. Code and Python
specialists approved the same four source/test SHA-256 identities.

Tests exercise the actual localhost HTTP handler on isolated runtime homes:
adaptive clerical selection, architectural review, malformed review answers,
mode transitions, quoted-mode exclusions, lease invalidation, selected effort
controls, provider retry restoration and operational overrides.

Direct TypeSafe synthetic classification checks observed:

| Case | Model | Effort | Review |
| --- | --- | --- | --- |
| Uncertain hardware architecture | Astra | high | independent |
| Authentication migration plan | Astra | high | independent |
| Bounded feature implementation plan | Sol 6.1 | medium | independent |
| Spelling edit to an approved plan | Luna 6 | low | none |
| Authorized separable planning reviews | Astra | high | parallel |
| Simplify an overengineered architecture | Astra | high | independent |

These are predeclared classification regression expectations, not measurements
of completed software quality or project-wide token savings. The live checks
used synthetic public tasks; no private conversation or credentials are
included.

The restarted local service reported policy `split-v17-adaptive-plan`. A
synthetic native Plan envelope completed through the real localhost relay
and upstream model (HTTP 200, Sol 6.1/medium, independent review guidance).
This confirms the relay path, not an observed Desktop UI toggle.

The local embedded-router suite initially found an obsolete Codex CLI 0.40.0
whose `debug models` command is unsupported. Its real-app-server contract lane
therefore failed, while the other router tests passed. A pinned CLI run passed
its two subtests before encountering a differently versioned installed Desktop
CLI. Clean CI runners must verify the repository's pinned contract; no test or
platform lane is disabled to mask this local environment limitation.

## Rollback

Revert the policy commit and restart the Jev service. No catalog, authentication
or managed global configuration migration is required. Ordinary routing uses
the existing quality-sufficient project-token policy.
