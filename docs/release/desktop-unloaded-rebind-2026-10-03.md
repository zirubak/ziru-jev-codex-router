# Persisted unloaded chat provider switch

The Desktop bridge rejected persisted official chats whose native status was
`notLoaded`. New chats bypass that provider-crossing path. This is a confirmed
code defect; the original Desktop toast did not expose enough information to
establish that it was the only cause of the reported failure.

The bridge now resumes either an idle or unloaded persisted chat, requires the
resumed live session to be idle, and then applies the existing provider switch.
Permission provenance, exact permission comparisons, exclusive unloading,
rollback, and pending-route safeguards remain unchanged.

Two regression tests failed before the implementation and pass afterward:
unloaded official chat switching, and activity appearing during resume.
The native qualification also covers reopening a saved official route in a
fresh process, switching to Auto, and preserving read-only permissions.

Verification on macOS with Node 23.11.0 and Python 3.12.3:

- Python suite: 283 tests, one skipped, passed.
- Python compilation and routing evaluator passed.
- Focused bridge suite: 32 passed, two optional integration tests skipped.
- Signed bundled native CLI 0.160.0 qualification passed, including
  `unloaded-official-provider-switch`; eight synthetic HTTP requests,
  no normal automatic compactions, minimum context window 828400.
- Read-only code and Python specialist reviews found no blocking issues.

The initial default-Python attempts failed because macOS selected Python 3.10;
checks were repeated with Miniconda Python 3.12 on PATH. An optional older native
launcher test failed because its manifest fixture predates current qualification;
the current isolated native qualification passed. A qualification attempt during
full-suite load exceeded its deadline; its later run passed without increasing
the deadline.

The full Node suite ran 4557 tests: 4518 passed, 38 skipped, one failed.
The failure, `Windows and Linux never trust linked package ancestors or
resources`, raises `ERR_FS_EISDIR` in unchanged tray test cleanup. The identical
failure was reproduced in the original checkout without the runtime patch.
Final syntax checks passed; focused bridge and probe tests passed 39 with three
optional tests skipped.

Transactional installation results will be recorded after completion. The user
must restart Desktop and retry the original chat to confirm the visible symptom
is resolved.
