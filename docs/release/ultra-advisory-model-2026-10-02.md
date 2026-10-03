# Ultra advisory model label — 2026-10-02

The manual Ultra advisory now names its existing target inside the bracket:
`[Jev Ultra 추천: GPT-6.1 Sol]` or `[Jev Ultra 추천: GPT-6 Astra]`.
Model selection and API effort are unchanged. Exact old and new advisory
forms are removed from assistant replay; structured output remains protected.

## Candidate and checks

- HTTP RED: three expected label assertions failed before implementation.
- Public Python: 207 tests passed.
- Vendor Python: 244 tests passed.
- Python compileall and offline routing dossier passed.
- Embedded router syntax check passed; tests: 4417 passed, 31 skipped, 0 failed.
- Whitespace check passed.
- Integrated read-only code/Python review: APPROVE, candidate hashes matched.
- Runtime Python: 262 tests passed; syntax and offline dossier passed.
- Runtime activation: root installer with Desktop preparation passed; live smoke
  returned HTTP 200 / completed on gpt-6.1-sol. Desktop was not restarted.
- Installation preserved config.toml byte-for-byte against its transaction snapshot;
  jev.config.toml also matched the pre-task hash. Concurrent pre-install changes
  to the base model/effort and project settings were retained.
- Remote CI and merge are pending. UI screenshot verification was not performed.

## Candidate SHA-256

- `server/jev_server.py`: `604acfa9774786a71df10a66c5a1abee2d86523be930c80791c41399852f7431`
- `server/ultra_advisory.py`: `b225d33bb155e28b5c5b472e3645efb8e52181bbccf2d914118cd564f1c2c3c9`
- `server/test_ultra_advisory.py`: `4515c8096b38ca6c2c8fa29c3f97bc968a96315bc729483dfde55e4bc2c9dc55`

No durable learning: behavior and compatibility are recoverable from code and tests.
