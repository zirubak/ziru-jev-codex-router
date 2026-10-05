# PR25 integration preparation and limits

The tested local integration combines PR25 `a9167f90c36fe4fe7af9b074c2b855c19414ac66`
with PR23 `2efe3b363b4cf7ff43aa95a26477bc1f6413836f`. PR23 was squash-merged
as `0bc3e8e95195dc5f3ba18251c43b0a16faf69be5`; its Git tree is identical to
the tested PR23 source. The shared merge base is
`31000d05ef2314f7332d60578c24e19906bdf424`.

The prepared integration tree was `1d6a516462026043a9f07ca1f22eb8aec3fc235a`.
Its single probe conflict preserves both unloaded official switching and the
separate compaction safety hard stop. Canonical manifests, typed-only recovery,
signature/artifact binding, request ownership checks, permission provenance,
exclusive unloading, rollback, sandboxing and process retirement are retained.
This documentation addition changes no executable source or tests.

Independent isolated macOS checks on that prepared source used macOS 27.0.1
arm64, Node.js 24.21.0, Python 3.12.11 and umask 077:

| Check | Result |
| --- | --- |
| Python unittest discovery | Exit 0; 283 total, 282 passed, 1 skipped |
| Python compileall (server and poc) | Exit 0 |
| Routing evaluator | Exit 0 |
| npm run check | Exit 0 |
| Full npm test | Exit 0; 4,611 total, 4,573 passed, 0 failed, 38 skipped |
| Independent actual responder/launcher localhost harness | 12 passed |
| Independent integrated code and Python specialist reviews | No blocker in the prepared integration |

The two unloaded/active-on-resume regressions and canonical-manifest hard-stop
tests passed. Dependencies came from an approved locked cache without install
scripts; existing Chrome used a temporary test profile. No credentials, paid
model request, real app installation/restart or settings changes were used.

Node skips: 27 Windows-only, 2 Linux/systemd-only, 2 optional LiteLLM integrations,
5 real native binary/catalog integrations, 1 real Codex HTTP integration and
1 optional PyYAML round trip. The Python skip requires a separately acquired
signed Desktop fixture. Skipped assertions are not passing acceptance evidence.

The additional native unloaded-switch probe path and its completion within the
18-second overall probe deadline have not been executed for this integration.
Signed Desktop/native UI, actual inference/compaction/restart and deployed
installer acceptance remain unverified. Earlier installation and smoke reports
are historical revision-specific evidence, not acceptance of this source.
The older tray ERR_FS_EISDIR baseline assertion lacked an exact original SHA;
this full suite did not reproduce it but does not establish its original cause.
The requested repo-maintainer named workflow was unavailable and is not claimed
complete. Twelve unchanged non-executable media files were omitted locally,
with their original Git tree metadata retained.
