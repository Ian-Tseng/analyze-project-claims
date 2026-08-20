# Codex Plugin Quality-Loop E2E Log

Status: v0.8.0 CANDIDATE LOCALLY CONTRACT-TESTED; LIVE HOST CONTINUATION NOT YET OBSERVED
Parent baseline: v0.7.1 / commit `2fdb33afe5db23827dabe9addf718bb6020176f1`

## Local evidence

- Repository-root plugin manifest and marketplace shape: tested.
- One `Stop` handler, no ignored matcher, one-second timeout: tested.
- `PLUGIN_ROOT` code location and `PLUGIN_DATA` private state: tested.
- Exact final-line marker extraction: tested.
- `stop_hook_active`, analyzer-origin, and depth guards: tested.
- Same session/turn produces at most one continuation response: tested.
- Receipt replay creates one proposal: tested.
- Sixteen concurrent replays create one proposal: tested.
- Oversized hook input is a no-op: tested.
- Offline fixture sends nothing: tested.
- Official local plugin validator: passed.

These checks do not prove that a released Codex host trusted the hook, invoked
it, accepted its continuation request, routed the continuation to the named
skill, or activated a plugin update.

## Required live record before automatic-Codex claims

Record:

1. Codex version, OS, plugin source and version;
2. marketplace installation and plugin enablement;
3. `/hooks` review and trust of the exact handler hash;
4. a disposable producer result ending in one valid receipt marker;
5. one continuation request and resulting local proposal;
6. replay, `stop_hook_active`, second matching hook, and veto recovery;
7. measured hook p50/p95 and maximum runtime;
8. plugin N to N+1 replacement and new-thread activation.

If routing or another hook prevents continuation, record
`CONTINUATION_NOT_OBSERVED`, preserve the receipt, and run explicit `consume`.
Do not describe that outcome as automatic analysis.
