# Fixed-model routing boundary corrections

Review of the fixed Sol and Astra routes found five gaps beyond the initial
happy-path coverage. The corrections preserve Auto/Manual behavior and the
existing fixed-model execution contract.

- Switching Sol to Astra and back could revive the first Sol effort lease.
  Session selection changes now discard the previous lease. A bounded request
  tracker prevents superseded in-flight requests from reading, changing,
  restoring, or deleting a newer decision. Tracker eviction also drops its lease.
- A fixed route could reuse an effort lease after its Jev key became unavailable.
  Missing keys now invalidate the lease before selected-model/high execution.
- A native HTTP 200 containing a failed terminal cleared automatic quota state.
  Recovery now requires `response.completed`; failed, incomplete, and missing
  terminals retain the automatic state. Manual dry state remains authoritative.
- V1/V2 compaction aged long consumed tool outputs before the fixed route saw
  them. Fixed routes now retain the same canonical replay guarantee during
  compaction as ordinary requests, including evidence in the middle of a result.
- A Sol child with an explicit Astra model argument inherited the Sol provider
  but failed the native carrier check. Fixed-route subagent calls now inherit
  their parent's carrier/provider without explicit model or effort overrides.
  Jev still determines the child's execution effort. Other arguments are kept.

## Regression evidence

Isolated localhost HTTP tests first reproduced the failures. The regression
cases cover both fixed models, selection round trips, independent sessions,
missing-key recovery, superseded requests blocked before and after lease lookup,
bounded tracker eviction, and failed terminals with normal and Responses-lite
requests. Transport tests cover V1/V2 full replay and both child fork modes.
An isolated native child fixture also verifies the corrected carrier and scoped
provider, rather than inferring execution from tool arguments alone.

Run the required Python suite, compileall, routing dossier, Node checks and Node
suite for both the public candidate and the deployment candidate. Bind the
integrated code/Python verdict to file hashes. A correction after the full suite
requires the affected checks and an updated verdict on those exact files.

Private deployment policy stays outside the public change. Installation uses
the root transaction from a permanent checkout and preserves official provider
isolation. Verify both fixed routes with real TypeSafe-to-native completed
responses after installation. Desktop restart and visible picker confirmation
remain separate from backend verification.
