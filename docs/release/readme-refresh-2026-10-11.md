# README and routing illustration verification — 2026-10-11

Base: `f38b992dee5e3ea7f1675e4e3fd2ab6af71cd139` (`v0.1.0-preview.3`).
This update changes documentation and a static illustration only.
The published preview tag and runtime behavior are unchanged.

## Scope and checks

- English and Korean README descriptions cover Auto, Manual, Jev Sol and Jev
  Astra, including effort controls, model-specific fallback, Plan guidance,
  Ultra boundaries and route-label limitations.
- The linked Desktop integration guide lists all four current models/providers
  while retaining the historical Auto/Manual UI acceptance boundary.
- Public HTTPS source access was checked without Git credentials. Shell
  examples pass syntax checks; installation commands were not executed.
- Local document links and heading anchors resolve. Asset dimensions and
  SHA-256 match the manifest. Changed text passes whitespace checks.
- The 2172×724 four-panel comic was visually checked: Manual locks High while
  the model remains selectable; Sol/Astra fix the model while effort adapts.
  The illustration does not establish actual UI or inference behavior.
- TypeSafe terminology and the key-page link were checked against its
  [coding-agent explanation](https://docs.typesafe.ai/introduction/coding-agents)
  and [quick start](https://docs.typesafe.ai/introduction/quickstart).

## Reused runtime evidence and limits

The runtime tree (`server/`, `router/`, `poc/`, `install.sh` and `bin/`) matches
`v0.1.0-preview.3`. Existing [release checks](v0.1.0-preview.3-verification.json)
are reused for those unchanged inputs; full runtime suites were not rerun for
this documentation update. No installation, Desktop restart or live inference
was performed. GitHub Actions remains disabled; no remote CI pass is claimed.
The existing [preview limits](v0.1.0-preview.3.md#dependency-audit-and-known-limits),
including Desktop Plan issue #30 and build-time dependency advisories, remain.

## Candidate identity

The table identifies the documentation and asset candidate relative to the base.
This verification record is excluded from its own hash table.

| File | SHA-256 |
| --- | --- |
| `README.md` | `686cf09a07436be4a74c8051402dccd420a38ddd8d07d9e4c6750e29de556dc2` |
| `README.ko.md` | `684a8dd264f162549c753bffa260703516f4c3a313e534c19f279ccbefebee05` |
| `docs/assets/PROVENANCE.md` | `9e95f5cfc239d9a93343568c27d7c5185833c46cbef1708a438d82bc7366b336` |
| `docs/assets/manifest.json` | `2d844fff196584e958fe0893e82da2a9d58c49330873a6a3689c1ca3735e36ab` |
| `docs/assets/routing-modes-comic.png` | `8401681e8c172911a4dd97c5d380026b5a1eff9f5de14a473f631344947759ee` |
| `docs/release/native-desktop-bridge.md` | `95f8b3e0a5f94c43bff6e65f9bf85434c4902085857e3ba0985bae597850f0f3` |
