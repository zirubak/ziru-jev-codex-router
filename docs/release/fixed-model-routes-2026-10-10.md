# Fixed-model routes with adaptive effort

`jev/sol` (Jev Sol Router) pins GPT-6.1 Sol; `jev/astra` (Jev Astra Router)
pins GPT-6 Astra. Auto and Manual retain their existing behavior. Sol's fixed
route also stays Sol for architecture/final/risk reviews. Jev judges effort
within the selected model's capability; it does not select a different model.

## Execution contract

- Fixed routes send only effort and lease questions. Native Plan adds a review
  recommendation and re-evaluates every call. The model profile and bounded task
  dossier are evidence; canonical execution history remains intact.
- Valid efforts are low, medium, high, xhigh and max at standard speed. An incoming
  numeric effort is ignored. No automatic Ultra or cross-model advisory is added.
- Jev/schema/key/task failures use the same selected model/high. Kill skips Jev;
  shadow records the hypothetical judgment but executes same-model/high. Kill
  takes precedence. Historical reasoning updates cannot override those controls.
- Native errors never invoke a different model. An automatic quota cache permits
  one native recheck per request; success clears automatic state. Manual dry
  remains authoritative. Existing rate-limit/quota classification is unchanged.
- Both the outer fixed route and its exact native re-entry prohibit model swaps,
  including aliases, redirects, cooldown, compaction and post-error failover.
  Same-model transport recovery retains its existing behavior.

## Desktop and upgrade acceptance

The picker publishes four routes. Selection survives native notifications,
provider switches, fork/resume and bridge restart, while official defaults and
permissions remain isolated. Sol is still the Desktop metadata carrier and is
not proof of the model that executed a fixed Astra request. Native qualification
must exercise all four modes after the bridge digest changes.

The installer recognizes only structurally owned old two-provider and new
four-provider recovery blocks. It preserves unrelated bytes, rejects foreign
provider definitions, and restores the original block on failed installation.
Repeated installation is idempotent. The root transaction remains the supported
installation path; Desktop is never restarted automatically.

## Verification procedure

First observe isolated localhost HTTP RED, then GREEN for both models and five
efforts, invalid/missing judgments, stale updates, operational flags, leases,
quota recovery/refusal, and full image/tool/Responses-lite replay. Verify zero
cross-model attempts with native aliases/redirects and router failover enabled.
Exercise Desktop lifecycle and the two-to-four provider upgrade with rollback.

Run the repository-required Python suite, compileall, routing dossier, Node syntax
checks and Node suite. Freeze source hashes for the public candidate and the
deployment candidate with any preserved private local policy. Those different
trees each require checks; one integrated code/Python review covers their diff.
Private local changes and runtime evidence do not belong in the public commit.

After the root installation, check catalog, isolation, service source identity,
and `python3 server/smoke.py --route sol` / `--route astra`. Require HTTP 200,
the exact selected model and `response.completed`; inspect only sanitized route
and effective-effort metadata in the private decision log. API verification does
not establish that the current Desktop process loaded the new picker. Report
Desktop restart/screen verification separately when pending.

No savings or comparative model-quality claim is established by these wiring
checks. GitHub Actions remain disabled by the owner's existing instruction;
local checks and integrated review are the merge gate.
