# Private preview verification

Release candidate: `eb3101bc8697bb5a43e2950cbb5577720f76600d`.
Local verification date: 2026-10-01 (America/Los_Angeles).

- Python server: 206 tests passed; byte compilation passed.
- Installation focused checks: 18 tests passed; code and Python specialist
  reviews approved the behavior candidate `47a2aa1`.
- Offline routing dossier: passed without TypeSafe calls.
- Root `./install.sh --prepare-only`: passed from this checkout. This is
  preparation evidence, not a live installation claim.
- Embedded syntax checks passed; production dependency audit found zero
  vulnerabilities.
- The initial local full Node suite reported four failures: missing Playwright
  after prepare-only removed development dependencies, and the discovered
  legacy Codex 0.40.0 lacking `debug models --bundled` (two children and their
  parent). After `npm ci`, all 15 desktop-panel tests passed. The current
  Desktop Codex 0.159.2 contract cases passed in the original suite.
- GitHub CI run `36960481117` tests the pinned Codex 0.155.0-alpha.9.2,
  Python on Linux/macOS, and the full router suite on Linux/macOS/Windows.
  Its final status must be checked separately; this file is not a CI verdict.
- Repository visibility was confirmed private after push.
- Secret scanning activation was rejected by GitHub with HTTP 422:
  `Secret scanning is not available for this repository.` Local staged-content
  scanning and runtime exclusions remain active. Do not claim GitHub push
  protection was enabled.
- All three brand images are tracked with dimensions and hashes in
  `docs/assets/manifest.json`. The banner was visually rechecked.
- Social preview settings upload is pending: the in-app browser is signed out
  of GitHub and cannot access this private repository's settings. The prepared
  image is `docs/assets/social-preview.png`.
- Existing user services were not replaced to qualify this release path.
  No new live installation or bad-key network response is claimed.

No durable learning: release boundaries and fixes are recoverable from the
source, tests, and existing documentation.
