# Release test record template

Copy this file for each candidate/run. Do not overwrite historical evidence or
mark a case passed because its procedure exists. Use the stable IDs from the
[system/integration/release catalog](system-integration-release-tests.md).
Keep private captures outside version control; publish reviewed summaries only.

## Candidate and scope

- Record ID / date / time zone:
- Owner / reviewers:
- Product scope and accepted exclusions:
- Source commit / branch / dirty-file hashes:
- Dependencies / Node / Python / OS versions:
- Desktop build / native executable version and SHA256:
- Supported profile CLI version/path identity:
- Installed runtime identity / selected file hashes / declared private overlay:
- Loaded adapter identity and how it was verified:
- Protected config/profile/app/backup before hashes (no contents):
- Required case IDs and reason for selection:
- Reused case evidence, unchanged-input comparison and limits:
- Private evidence manifest locator and SHA256 (private copy only):
- Public sanitized artifact links and hashes:

## Case results

One row per case and layer; expand Manual effort subcases to five rows. Valid
statuses: PASS, FAIL, BLOCKED, NOT RUN, SKIP. Record unavailable prerequisites as
such. Fixture/native/live/UI results must not be combined into one PASS.

| Case ID / subcase | Layer | Status | Actual command or steps | Expected / observed | Evidence run and artifact hash | Limitation / failed-attempt reference |
| --- | --- | --- | --- | --- | --- | --- |
| INT-01 | F/N | NOT RUN | | | | |
| SYS-04 / low | L/U | NOT RUN | | | | |
| SYS-04 / medium | L/U | NOT RUN | | | | |
| SYS-04 / high | L/U | NOT RUN | | | | |
| SYS-04 / xhigh | L/U | NOT RUN | | | | |
| SYS-04 / max | L/U | NOT RUN | | | | |
| SYS-07 / same-response identity | L/U | NOT RUN | | | | |
| REL-08 | R | NOT RUN | | | | |

## Correlated live execution record

Use one row per actual upstream execution, including tool continuations. IDs
and private joins may be retained in the private record rather than published.
Do not join by time alone. Do not confuse the current answer with a probe it
runs to describe another execution.

| Run / role (outer answer or separate probe) | Thread / turn / native item | Request / response / message IDs | Input mode / effort | Fresh Jev response or lease source | Applied model / effort | Actual response metadata | Visible prefix for same message | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

Record field absence/conflict explicitly. A requested model is not executed
model evidence. If the upstream does not return the required metadata, mark
the conclusion unverified and state what boundary can actually be established.

## Tool roundtrip record

| Run / request join | Tool schema hash at ingress | Hash at relay receipt | Hash before execution | Tool call ID / schema-only enum match | Callback-created nonce / final exact match | Native final message join | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

- Canonicalization/hash method:
- Schema enum excluded from user prompt:
- Result nonce generated only inside callback:
- Actual TypeSafe endpoint/model and bounded dossier fields observed:
- Count of fresh TypeSafe calls, lease reuses and upstream executions:
- Tools were relayed to execution; whether TypeSafe saw only bounded summaries:
- Capture method preserves production decision/payload behavior:
- Collector terminal-flush/cleanup evidence and test-owned process scope:

## Installation and restoration

- Root transaction invocation / first result / second idempotence result:
- Parsed TOML / official provider isolation / profile isolation verdicts:
- Protected config/profile/app/backup after hashes and comparison:
- Manifest/pins comparison and external route-state location:
- Failed-install fixture results and any restoration limitation:
- App process unchanged / user-controlled restart evidence:
- Original unrelated WIP and private runtime overlay preservation:

## Checks, review and release decision

| Check | Candidate/input identity | Pass / fail / skip totals | Exit status | Evidence | Reused or executed now |
| --- | --- | --- | --- | --- | --- |
| Python suite / compile / offline dossier | | | | | |
| Node check / full suite / native protocol | | | | | |
| Affected reruns after corrections | | | | | |
| Dependency / staged-secret / diff checks | | | | | |
| Integrated review | | | | | |
| Actions enabled/disabled and retained CI evidence | | | | | |

- Failing/aborted attempts and verified explanation:
- Unresolved mandatory case IDs and completion condition:
- PR URL / tested head / draft or ready / merge result:
- Overall status: PENDING until required current-candidate gates are satisfied.
- Completion decision and evidence (do not infer from test count alone):
- Learning judgment: existing code/tests/docs suffice, or exact saved lesson:

A disabled or billing-blocked CI run is not a successful run. The current owner
policy uses local checks and integrated review for merging. A successful local
probe is not native slider acceptance. A commit, push, installation and merge
are distinct outcomes. Do not schedule an automatic restart or add unrelated
work merely to fill this template.
