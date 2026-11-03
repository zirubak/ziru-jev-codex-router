# Opt-in Fast serving for fixed Sol/Astra routes

## Design and impact

Standard remains the default. Jev Sol Router and Jev Astra Router accept explicit
Fast selection independently of Jev-selected reasoning effort. Auto/Manual stay
Standard-only. The native Desktop catalog supplies supported Fast metadata;
capabilities are retained across model-list pages and refreshed with the catalog.
The CLI/router overlay advertises the opt-in priority tier for fixed routes.

The shared router normalizes the fast alias only for these fixed routes and only
for an advertised tier. Invalid fixed-route tiers fail before gateway dispatch.
Jev validates speed before judgment, preserves it across same-model technical
fallback and tool continuations, and never changes the fixed model to rescue a
Fast refusal. Native provider switches retain the existing serviceTier handling.

A requested speed is not an observed served speed. Terminal metadata is recorded
separately, including Standard downgrades and unknown tiers. New unconfirmed Fast
records are excluded from cost estimates. Historical speed assumptions remain
unchanged. Response labels continue to show model/effort and do not claim Fast.

## Verification boundaries

Tests use isolated homes, synthetic credentials and loopback responders. No
production service or account configuration is changed by this PR. Native
protocol qualification checks persistent Fast selection, resume, persistent
Standard reset, permissions and canonical replay with the bundled native client.
It does not measure real backend latency or establish account entitlement.

To verify an entitled live account after installation, run:

```sh
python3 server/smoke.py --route sol --speed fast
python3 server/smoke.py --route astra --speed fast
```

These consume usage. Both must confirm fixed-model identity and terminal Fast
service metadata. Desktop picker appearance still requires visual verification.
The ordinary signed-app qualification remains fail-closed with its existing
signature and native-probe deadlines; no safety boundary is relaxed.

## References

- [Codex speed](https://learn.chatgpt.com/docs/agent-configuration/speed)
- [API Fast mode and served-tier metadata](https://developers.openai.com/api/docs/guides/fast-mode)

## Local validation

- Test-first failures reproduced missing Fast forwarding and missing picker
  capabilities; five Fast HTTP tests and two picker tests then passed.
- Python full suite: 395 tests, one skip, three installer-fixture timeout errors.
  All three failing cases passed a separate isolated rerun. Compilation and
  routing evaluation passed. Five smoke tests, including served-tier proof,
  passed after adding the final smoke regression.
- JavaScript syntax/config checks passed. Full Node run: 4,870 tests; 4,821
  passed, five failed, one cancelled, 43 skipped. Gateway cleanup/timeouts
  resolved in a 164-test isolated rerun. Routing's original three health timeouts
  passed its whole-file rerun; two different health timeouts in that rerun then
  passed a two-test isolated run. The full run is not entirely green.
- The remaining tray cleanup `ERR_FS_EISDIR` failure reproduced in the unchanged
  original checkout. It is recorded rather than hidden or fixed in this PR.
- Required integrated and Python specialist code reviews approved the changes.
- Final native protocol probe passed with codex-cli 0.162.0-alpha.17.2, 22
  synthetic requests, zero compactions, and both fixed-route Fast persistence /
  resume / Standard-reset checks. Existing recovery and permission checks passed.
- Strict signature verification with the OpenAI signing requirement succeeded
  in 9.30 seconds. Combined signed-app qualification hit its existing five-second
  signature deadline; that deadline remains unchanged. The native probe above
  is separate evidence, not a successful combined qualification receipt.
- No real-account Fast inference, latency benchmark, billing measurement or
  visual Desktop control verification was performed. Keep the PR in draft until
  those product checks and normal signed qualification are verified.
