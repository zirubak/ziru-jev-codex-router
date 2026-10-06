# Issue #30: native Plan detection and reset diagnostics

Status: partial remedy. The owner reports that Plan disappears immediately after
selection, before sending. Isolated actual native protocol tests do not reproduce
that GUI symptom; [issue #30](https://github.com/zirubak/ziru-jev-codex-router/issues/30)
remains open. Do not call this a complete UI fix.

## Confirmed defect

The bundled `codex-cli 0.160.0` sends a trusted developer envelope starting
`<collaboration_mode># Plan Mode (Conversational)`. The server recognized only
the older `# Collaboration Mode: Plan` heading, so current native Plan requests
missed the adaptive planning questions and guidance. Recognize the exact new
heading inside the existing trusted, unfenced, top-level envelope. Later Default
notices still supersede Plan; user/tool text and quoted examples cannot enable it.

## Verification boundary

The actual native-to-loopback-router HTTP test failed on the server Plan boolean
before the parser fix and passed afterward for Auto and Manual. Settings
notifications already retained Plan before that change. The test also checks
Plan effort changes and return to Default. A separate synthetic persisted
history test resumes a non-Jev provider, switches to Auto/xhigh and selects Plan
without sending another model request. Both confirm protocol behavior, not GUI
rendering or a complete account-backed UI turn.

Final local checks passed: Python 284 PASS/1 optional SKIP, Node 4,613 PASS/43
conditional SKIP/0 FAIL, actual native focused tests 3 PASS/0 SKIP, syntax,
compile, offline dossier, production audit and whitespace checks PASS. One
integrated code/Python review approved the exact final candidate. Signed
Desktop qualification passed. Native fixture
inputs come from a private immutable official-model snapshot. The existing
native pressure test's known unknown-model-window mismatch is not repaired or
used as evidence of this fix. Repository Actions remain disabled.

## Private opt-in diagnosis

After installing with `./install.sh --desktop`, the owner must fully quit and
reopen Desktop using `Jev Codex.command` so it loads the new adapter. The
installer does not restart Desktop.

Create an owner-only empty `plan-diagnostics.enabled` file beside the private
Desktop manifest. The adapter records client/native requests, native replies
and raw/public settings-notification boundaries in `plan-diagnostics.jsonl` in
that same directory. Only whitelisted mode/model/effort values, method/event,
UTC time, numeric error code and a thread hash are recorded. No prompt, tool
content, account identifier, raw thread ID, credential or arbitrary model string
is recorded. Files require owner-only regular-file permissions, links are
refused, and recording stops at 1 MiB. A failed recorder is isolated from routing
and emits a bounded warning. Remove the enable file to stop recording.

The next evidence gate is one actual immediate-reset reproduction with this
metadata trace. Diagnose the authoritative settings transition before changing
mode preservation behavior. Keep diagnostic logs private; publish only reviewed
summary findings. No durable learning: behavior and limits are recoverable from
source, tests and this document.
