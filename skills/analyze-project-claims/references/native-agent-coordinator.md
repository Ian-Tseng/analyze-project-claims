# Executable native-agent coordinator

`native_agent_coordinator.py` connects the existing pool controller to an explicit trusted host provider. It harvests every available terminal, quiescent result before dispatch, persists the actual envelope, finishes the exact token, reuses a role-compatible identity, binds before starting, and checks readiness immediately before host execution. Workers and their reviewers remain distinct.

This is an opt-in executable adapter. Installing the skill does not wire the host tools to Python, start a service, activate this adapter, or add a close capability. The existing tool-driven host protocol remains supported. Never describe the Python tests as native AI review or host-capacity verification.

## Entry points

From the skill scripts directory, a host integration can invoke:

```python
from long_running_controller import Controller
from native_agent_coordinator import NativeCoordinator

coordinator = NativeCoordinator(Controller(existing_state_path), host_provider)
result = coordinator.run(max_ticks=100)
```

Or explicitly load a trusted Python provider already on the Python import path:

```text
python native_agent_coordinator.py --state STATE --adapter YOUR_MODULE:create_host --max-ticks 100
```

`create_host(controller)` returns the provider described below. No provider is loaded implicitly, downloaded, or included for the current Codex collaboration API. This command executes the explicitly selected Python module with the caller's permissions.

Call again after host result/capacity events or recovery. `run` refills after STARTED, then returns on waiting, ambiguity, pause, stop, completion or its finite tick budget. It does not busy poll. The dispatch budget and all existing source/claim gates remain controlling. Only one coordinator can tick a state at a time; do not run another native tool dispatcher against that state concurrently.

## Host-provider contract

All methods must impose finite I/O timeouts, retain actual host receipts, and normalize observations without inventing quiescence, capabilities, outcomes or identities. The provider is trusted integration code; structural checks cannot authenticate its declarations. Source references identify retained host evidence. Agent IDs are scoped to this controller's host/session. Observe may include unrelated agents; they are never adopted or closed by the coordinator.

- `observe()` returns the exact observation schema in subagent-host-protocol.md: observed_at, source_ref, close_supported, agents. Each agent has agent_id, normalized status and execution_quiescent. Preserve tombstones with status closed when verified by the host. Absence alone is not closure.
- `find(token)` returns actual token-matching host IDs, including a suspended unbound spawn left by a lost reply. Return all matches; ambiguity blocks dispatch. An empty result does not prove a timed-out spawn created no agent.
- `spawn(request)` returns an actual new agent ID, initially suspended awaiting start. Preserve the complete request and token-bearing native identity. Do not start task work before the durable bind/start handshake.
- `start(agent_id, request)` starts or wakes that exact identity with the complete fresh request and returns a real acknowledgement source reference. The agent also performs the request's readiness preflight. A queued message without execution acknowledgement is not a receipt. This method must never spawn a replacement agent.
- `result(agent_id, token)` returns None until an exact result can be retrieved, or an envelope with exactly agent_id, token, source_ref and result. Return the actual worker/reviewer JSON; do not fabricate claim updates or skill invocation. Completed failed/cancelled agents still need a valid result. A terminal status with unresolved child operations is retained.
- `close(agent_id)` invokes a documented native release operation and returns exactly source_ref and boolean closed. It must not interrupt agents, archive task trees as a substitute, delete evidence or reenter the controller. Closure is accepted only after a fresh normalized closed observation; even a positive acknowledgement alone is insufficient.

## Persistence, retention and recovery

Lifecycle transition observations, result envelopes with harvest observations, assignment intents, delivery intentions/acknowledgements and close intentions/outcomes live under native_lifecycle in the existing hash-linked journal. This is operational evidence, not another claims authority. Repeated identical waits do not append lifecycle events; inventory timestamps describe the last recorded transition, not continuous monitoring. The adapter's source is included in the reviewer contract. Changing it can require normal source-freshness recovery; do not rewrite earlier journals or bindings.

While work remains, count busy or held identities against their role budgets before retaining reusable agents: at most max_workers worker identities and one reviewer. Reuse requires all previous results recorded, fresh quiescence, matching role, no unresolved close and the controller's reviewer exclusions. Before new spawning, account for all owned identities lacking a verified closed observation; the retained-identity ceiling is max_workers + 1. Existing excess completed identities can be closed when eligible. If release is unavailable or unresolved and no suitable identity can be reused, return WAITING_FOR_CAPACITY. This ceiling is conservative; it is not a claim about the host's actual global thread limit.

After current goal completion, release every eligible owned terminal agent if supported. Task completion and resources_released remain separate. CLOSE_UNAVAILABLE, RECOVER_CLOSE, unresolved execution and missing observations remain visible. Pauses prevent starting work; safe result harvesting and eligible resource housekeeping preserve the pause and evidence.

Record intent before every spawn, start and close. A lost response causes identity/result recovery, never blind resending. A recovered exact spawn identity is durably attributed to this adapter and bound before start. Existing bindings with controller start acknowledgements, or without this adapter's assignment intent, are recovered without sending start. Missing/running/nonquiescent host observations also prevent start. A persisted harvested envelope is replayed through normal finish validation after fresh terminal/quiescent observation even if the host no longer retrieves the result; conflicting result contents remain an error. General spawn exceptions remain uncertain; the adapter does not infer a definite thread-limit rejection. Use the existing documented controller reconciliation/capacity-evidence protocol for capacity retries; this adapter does not automatically retry ambiguous or rejected calls. A delivery interrupted by an observed pause before calling the host is explicitly not_started; an ambiguous delivery stays held. A close with no verified closed observation is never retried or reused automatically.

## Verification limits

The deterministic coordinator tests execute the real controller, journals, reports and adapter with a synthetic host and reviewer. They cover full work/review/reuse/final-cleanup journeys, restarts, lost responses, pauses, freshness, identity conflicts and unrelated agents. Actual model review, native API integration, resource reclamation and operating-system memory effects need a separately observed host-provider integration test. The earlier live two-turn probe established reuse and retained completed status only; it did not establish a leak or release.
