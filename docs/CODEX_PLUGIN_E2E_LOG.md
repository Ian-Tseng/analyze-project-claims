# Codex Plugin Quality-Loop E2E Log

Status: v0.8.1 LIVE STOP INVOCATION FAILED; v0.8.2 CANDIDATE LOCALLY VALIDATED; SUCCESSFUL CONTINUATION NOT YET OBSERVED
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

## 2026-08-21 v0.8.1 Windows live observation

- Host: Codex CLI 0.148.0 on Windows.
- Installed plugin: `analyze-project-claims` v0.8.1 from marketplace
  `ian-tseng-analyze-project-claims`, repository commit
  `f15311473e33d15f0ab9eee5a4bfca385ff4c5db`.
- A fresh interactive session discovered and invoked
  `audit-venue-submission` v0.1.1, whose final response ended in one valid
  content-free `no_issue` / `requested_action: none` receipt.
- Codex visibly started the plugin Stop hook, then reported
  `hook exited with code 1` under the one-second handler timeout.
- The exact installed hook script processed a fresh equivalent receipt in a
  controlled local run in 251 ms, returned `{}`, and exited 0.
- The live failure is bounded to the host wrapper path; it did not inspect a
  transcript or project file, create a proposal, or perform an outbound action.
- The v0.8.2 candidate raises only the synchronous local handler timeout to
  five seconds. Fresh installed-plugin activation must be observed before
  describing the regression as resolved.
