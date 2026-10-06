# Native host protocol

This contract joins the durable controller to a host that exposes native
subagents, such as the `collaboration` tools. Use it only for an authorized
claims-guided goal with `subagent_mode` configured. The parent coordinator owns
the controller state. Delegated goals default to pool scheduling; independent
work can overlap within scoped locks and actual host capacity. Explicit serialized
mode retains one active token and one delegated worker or reviewer.

Include [evidence-guided agents](evidence-guided-agents.md) and the scoped claims
in each handoff. Provisional targets guide investigation; only declared execution
prerequisites require current support. The coordinator commits shared updates.

Use [agent-pool mode](agent-pool.md) for default delegated scheduling, automatic
legacy migration, scoped reviews and new-task identity reuse. Use durable dispatch
intents for resumed delegated goals too. The scalar loop and same-unresolved-task
reuse rule below apply only while executing the serialized contract.

## Coordinator loop

Use the packaged `scripts/long_running_controller.py` with the existing goal
state; the [startup example](subagent-mode.md#synthetic-startup-example) initializes a
synthetic example. In the following commands, `$ClaimsController` and
`$ClaimsState` refer to those actual paths.

1. Inspect `next`. On `DISPATCH`, retain the exact persisted request and token.
   Do not reconstruct a smaller request that drops scope, evidence, holds,
   limits, claim dependencies, or reviewer-source bindings. The request includes
   `role`, `working_claims`, `reviewer_contract`, `required_claim_updates`,
   `last_work`, and `delegation_key`. Use `role` to route the handoff.
2. Run `check --token TOKEN`. Dispatch only on `READY`. `STALE` requires the
   base protocol's not-started/failed-review handling and a fresh review;
   pause or stop prevents execution. Do not silently run the old request.
3. Inspect the current host for an existing task bearing this token (including
   an unbound task left by an earlier host call). Recover it if present; do not
   reserve another spawn. Otherwise reserve one call durably:

   ```powershell
   py -3 $ClaimsController --state $ClaimsState spawn-attempt --token TOKEN
   ```

   Only the invocation returning `SPAWN_RESERVED` permits one native call.
   Recheck `check` immediately before that call; a pause or source change still
   prevents spawning. Repeating `spawn-attempt` after a lost response returns
   `RECOVER_SPAWN`, not another permission. Use the recovery procedure below.
   Call the native `collaboration.spawn_agent` with a task name containing the
   token and the complete role-specific request. Use a worker for a work action
   and a `claims_reviewer` for a review. Tell the agent to wait for the
   coordinator's start message before doing task work. This separates spawning
   from the durable association of its host ID.
4. Persist the returned native agent ID against the token:

   ```powershell
   py -3 $ClaimsController --state $ClaimsState bind-agent --token TOKEN --agent-id HOST_AGENT_ID
   ```

   Recheck `READY`, then release the same bound agent to start. Use
   `collaboration.send_message` if it is still running/waiting, or
   `collaboration.followup_task` if it returned to idle; a message alone does
   not trigger a new turn in an idle agent. If binding fails, keep the spawned agent idle and reconcile the
   association before continuing. The agent's own preflight must also check
   readiness immediately before starting substantive work.
5. Receive progress and results with the native host's messaging/wait tools.
   While waiting, send normal user progress updates. Do not mistake a timeout,
   a missing message, or an agent's prose assurance for an observed outcome.
6. Validate that the returned result belongs to this request. The coordinator
   persists it as JSON and finishes the original token:

   ```powershell
   py -3 $ClaimsController --state $ClaimsState finish --token TOKEN --result result.json
   ```

7. Check completed agents and release eligible host resources using the lifecycle
   procedure below, then call `next` to continue the controller loop.

   Continue immediately after routine review and work results while eligible
   authorized work remains. Do not ask the user to repeat permission to
   continue. A work result triggers the next claims review before downstream
   work can rely on changed claims.

Native collaboration calls are host tool calls, not shell commands or functions
implemented by `long_running_controller.py`. The controller's command runner is not a native
agent launcher. Use this native protocol or an adapter that supports actual skill invocation,
tools, and the complete claim-update schema.
Do not invent an agent ID or treat request creation as proof that
a subagent ran. Retain actual host IDs and returned outputs for deployment
verification.

## Worker handoff

Include this instruction with the exact request:

> Wait for the coordinator's start message. Work only on the authorized action
> in this token. Read its instruction, declared execution prerequisites, provisional targets, affected
> claims, evidence scope, dependencies, holds, and limits. Call the controller's
> `check` for this token immediately before starting; proceed only on `READY`.
> Perform the substantial work unit and persist its actual output evidence in
> the declared project scope. Return `status` as `done`, `failed`, `uncertain`,
> or `not_started`, with what changed, evidence paths, observed verification,
> limitations, and any unresolved execution state. Do not modify controller
> state, clear claims, accept formal evidence, spawn further workers, or start
> unrelated work. Only the coordinator finishes this token.

A worker can inspect existing records and identify proposed claim changes, but
its completion does not establish those changes. Do not conflate a completed
implementation with a supported performance, reliability, or scientific claim.
For an explicit user pause, stop starting work and report the real state of
already-started operations; interruption alone is not proof that child processes
stopped.

## Claims reviewer handoff

Include this instruction with the exact review request:

> Wait for the coordinator's start message and check this token is `READY`.
> Actually invoke the active `analyze-project-claims` skill for this work unit:
> read the request's bound active SKILL.md, applicable user instructions, and linked
> guidance. Use the lightest sufficient audit depth and inspect the real
> claim-specific source locations, evidence, counterevidence, limitations, and
> dependent decisions. Review the request's required affected closure; preserve
> uncertainty and previous counterevidence. Keep lifecycle, scientific, and
> acceptance states separate. Return the complete base review JSON plus
> `skill_invocation` and `claim_updates` as specified in subagent-mode.md. Bind the
> request, source snapshot, and reviewer contract digests exactly. You are
> read-only: propose any necessary repairs or formal artifacts, but do not edit
> evidence, working claims, generated reports, journals, or accepted maps. Do
> not recursively launch repair or review campaigns. Only the coordinator
> commits your result and dispatches the next authorized action.

The reviewer checks every `required_claim_updates` ID and the dependent closure
of any extra updated claim, rather than merely echoing a worker's summary.
Any source or reviewer-contract drift makes all claims dirty conservatively;
all dirty claims need review before work is eligible. Preserve removed
counterevidence through explicit `superseded_evidence` dispositions and journal
history as described in subagent-mode.md. It can reclassify a previously supported
claim, retain an unresolved limitation, or withhold clearance. Supported claims
need direct matching support; contradicted claims retain their counterevidence.
A claim may remain untested after a useful implementation step.

A `skill_invocation` field is a digest-bound declaration, not cryptographic proof
of model behavior. The coordinator must observe the actual delegated skill
invocation and inspect returned coverage before claiming it happened. If the
skill or an applicable guide changed, refresh the request through the controller;
do not copy a new digest onto an old review.

The read-only role does not waive the installed skill's formal procedures.
When a formal audit requires reconciliation or persisted records, the reviewer
returns the proposal and concrete missing step to the coordinator. Keep the
review `PARTIAL` with explicit holds, or `FAILED` when required evidence cannot
be assessed; neither outcome establishes goal completion. Formal
component-map acceptance remains a human action; no automatic working-claim
update grants that authority.

## Recovery without duplicate work

On `IN_FLIGHT`, recover the existing token and request. Its association is in the
response's top-level `delegation` field, separate from `request`; it may be absent
if the token has not yet been bound. A binding records `agent_id`, `role`, and
`delegation_key`. Recover the actual associated host ID when one exists.
Use `collaboration.list_agents`, messages, and persisted outputs to inspect that
same agent. Reuse an existing agent only for the same unresolved task; do not
create a new worker merely because a wait expired or the parent restarted.

There is a possible crash between native spawning and `bind-agent`. The initial
wait-for-start instruction keeps such an agent idle. Search native agent state
using the token-bearing task name, then bind the observed agent before release.
If the host cannot establish whether execution started, retain uncertainty and
reconcile actual operation evidence. Never manufacture a fresh token or new
state directory to make the work appear unstarted.

If a worker's outcome is unknown, record `uncertain` for that same token and
inspect the actual operation before any retry. The controller's `reconcile`
command requires observed outcome or actual retry authority and retains repair
attempt history. Finishing a request while an agent might still be mutating
sources is not safe evidence finalization: first resolve its live execution state
or explicitly keep the work held. A reviewer failure leaves dependent work
uncleared and follows the existing finite retry policy.

`WAITING` means unresolved prerequisites, not completion. Continue independent
eligible actions when selected. User pause, stop, budgets, missing evidence,
missing authority, and exhausted repair attempts retain their original meaning.
A host process ending does not install a wake mechanism; cross-session recovery
requires its separately authorized existing adapter.

## Persistence and evidence boundaries

The coordinator commits working claim updates and derived reports through the
controller. Its journal-backed `working_claims` is the operational authority.
`<state>/reports/current.json` points to a digest-named revision containing
`claims.json` and each configured `<id>.md`, with their hashes. Read that pointer
instead of guessing which prior report revision is current. The controller
preserves historical journal events, failed outcomes, limitations,
and contradiction links. Generated projections belong in the state directory and
must never be added to their own declared source evidence. Downstream reports
are projections of the current reviewed working claims, with pending-review
state explicit; editing a Markdown report is not a claim update.

Formal scans use the installed skill's accepted component-map and audit-record
contracts. Populate `audit_refs` only with actual records and identify pending
formal steps. A locally passing orchestration fixture cannot prove independent
scientific replication, universal semantic review accuracy, fresh host
activation, or delivery of the entire goal.


## Exact binding fields

Copy snapshot, request and reviewer-contract digests programmatically from the
verified request into the persisted result; do not retype them through prose.
If a response is rejected for a transcription error, preserve the rejected bytes,
recheck the same pending request and evidence, and have the reviewer produce a
corrected result for that request. Never replace binding fields on an old result
merely to make it fit a different or stale request. A rejected transcription must remain recorded separately from its correction.


## Freshness of saved reports

`status` and report regeneration sample the declared evidence and reviewer contract.
The returned `freshness` and report projection distinguish CURRENT, STALE and UNKNOWN
source currency from the last recorded claim statuses. `review_required_claims`
includes all claims on drift or an unreadable source. Historical `complete` remains
a recorded decision; `freshness.completion_current` states whether it still applies
at the sampled identities. CURRENT identity alone does not resolve pending review.

An observation does not alter pending tokens, budgets, holds, pauses or accepted
claim decisions. `check` still blocks a stale worker; recover its existing token
before continuing. Saved reports describe the last sampled identities, not continuous
monitoring. Read status again before relying on their freshness. Earlier report
revisions remain historical evidence.

## Check completion and release host resources

At coordinator startup/recovery, after a result is persisted, before spawning a
replacement and when host capacity is exhausted, inspect the host's actual agent
list. On a long wait, use bounded waits and repeat the observation; do not busy
poll. Normalize observed native statuses to the schema below, retaining unknown
states as `unknown`. A completion message is not a resource-release receipt.

Harvest each result, verify its token/agent association, persist the actual output
and call `finish` before considering that agent for release. Failed and cancelled
agents also need a recorded outcome; unresolved side effects remain uncertain.
Inspect associated tool sessions and child operations: a terminal agent does not
prove its processes stopped. Do not mark `execution_quiescent` true without evidence.

Use the current native list and operation evidence to write a local observation:

```json
{
  "observed_at": 1790856000,
  "source_ref": "local-log/native-list-and-operation-check.json",
  "close_supported": true,
  "agents": [
    {"agent_id": "actual-host-id", "status": "completed", "execution_quiescent": true}
  ]
}
```

The timestamp is illustrative: record the actual observation's Unix time. Supported
statuses are `running`, `idle`, `completed`, `failed`, `cancelled`, `closed` and
`unknown`. `close_supported` means the current host exposes a suitable close/release
operation, not that an interrupt operation exists. Save the raw host response at
`source_ref`; the planner checks the declaration, not the truth of that observation.

```text
<python-3> <skill-root>/scripts/long_running_controller.py --state <state> agent-cleanup --observation <host-observation.json>
```

The command verifies the journal, requires an observation no older than 60 seconds,
and reports each bound agent. Unbound agents are ignored; missing, idle, live,
unrecorded or unresolved agents are retained. Any unresolved token using the same
agent ID prevents cleanup. The plan contains the observed journal sequence/digest
and recorded result digests; it changes no claims, reports, budgets or journal.

For `ELIGIBLE_FOR_HOST_CLOSE`, immediately recheck the actual host and current
binding/result state. If either changed, regenerate the plan. Only the coordinator
calls the host's documented close/release operation for that exact owned agent.
Record its returned outcome and verify closure or capacity release through the host;
a timeout or absent agent is not proof of success. Recover an ambiguous close by
inspection, not by interrupting or relaunching work. Never close a running agent,
parent, unrelated agent, or an agent with unresolved execution to free capacity.

If closing is unavailable, record `CLOSE_UNAVAILABLE` and leave host management to
the host; do not invent a close call or substitute `interrupt_agent`. Keep that
limitation explicit if capacity blocks progress. `ALREADY_CLOSED` records an
observed terminal host state and needs no additional close.

This cleanup releases host resources only. Preserve outputs, claim/evidence links,
source checkouts, journals and review history. Resource release may happen after a
worker's result is recorded and before the separate claims reviewer starts, which
allows the reviewer to use the freed capacity. It does not clear dirty claims or
permit dependent work before review. The reviewer's own recorded result is cleaned
up the same way without recursively launching another claims review.

## Recover `agent thread limit reached`

A host thread limit is independent of the 32-cycle repair budget and may count
retained threads as well as running agents. A finished agent is not necessarily
a freed slot. Do not increase concurrency, reset the controller, create another
conversation, or interrupt active agents to bypass it. For an owner-requested
session handoff, follow [session recovery](session-recovery.md); preserve the
existing controller, pending tokens and cumulative authority.

Before each native spawn, `spawn-attempt` reserves one attempt in the existing
hash-linked journal. New goals persist `max_spawn_attempts` (default **3 total
calls per token**, initial call included; configurable from 1 to 100 at init).
Older journals without this setting use 3 for newly recorded reservations;
this does not reconstruct earlier unrecorded host calls. Keep existing controller
bindings. Inspect historical calls before adopting this protocol for a pending
token; if its execution is uncertain, recover it instead of reserving a call.
The helper never launches agents and cannot intercept host calls that bypass it.

On an unsuccessful native call, preserve the raw response and record:

```json
{
  "attempt_id": "ID_FROM_SPAWN_RESERVED",
  "error": "agent thread limit reached.",
  "source_ref": "local-log/raw-spawn-response.json",
  "no_agent_created": true
}
```

```powershell
py -3 $ClaimsController --state $ClaimsState spawn-result --token TOKEN --result spawn-result.json
```

Use the actual diagnostic. Recognition is case-insensitive for the complete
`agent thread limit reached` diagnostic, with optional final period/exclamation.
Do not truncate another error into that phrase. `no_agent_created` must be backed
by a definitive host rejection; timeout, missing output, or an absent list entry
alone cannot establish it. Only that diagnostic plus confirmed non-creation
records `thread_limit`; other failures record `uncertain`. Preserve the raw host
source; declarations are validated structurally, not independently authenticated.
Recording a failure remains allowed after pause or source drift, without starting
work or changing the pending token, claims, review state, or work budgets.

For a confirmed rejection:

1. Inspect actual agents and associated execution; collect and persist completed
   results. Apply `agent-cleanup` and the native close procedure above only when
   supported and eligible. Absence of a close tool remains `CLOSE_UNAVAILABLE`.
2. If capacity has not demonstrably become available, retain this pending token
   and report `WAITING_FOR_CAPACITY`. Use bounded waits only while a real operation
   can change capacity; stop recovery on no progress, missing capability/evidence,
   pause, stale sources or exhausted budget. Waiting does not consume spawn calls.
3. After a verified capacity change, write a new observation:

   ```json
   {
     "host": {
       "observed_at": 1790856000,
       "source_ref": "local-log/fresh-host-list.json",
       "close_supported": false,
       "agents": []
     },
     "matching_agent_ids": [],
     "capacity_available": true,
     "capacity_evidence_ref": "local-log/verified-capacity-change.json"
   }
   ```

   Replace illustrative time/entries with the real host observation. Search
   token-bearing names and retained outputs as well as bound IDs. Include every
   matching identity even if capacity is free. `capacity_available` requires
   observed available capacity or confirmed release with the host's capacity
   semantics; merely requesting close, waiting or observing an idle agent is
   insufficient. Each retry requires new evidence after the last rejection.
4. Run `spawn-attempt --token TOKEN --observation recovery.json`. The helper
   requires an observation no older than 60 seconds and no earlier than the last
   rejection. A matching agent yields `RECOVER_SPAWN`; unavailable capacity yields
   `WAITING_FOR_CAPACITY`. Only `SPAWN_RESERVED` allows one call with the same
   request/token/role, after rechecking `READY`. On success, bind its actual ID
   and follow the normal START handshake. On failure, record that attempt's
   result. `SPAWN_BUDGET_EXHAUSTED` ends retries for this token.

A reserved call with no result or an uncertain failure yields `RECOVER_SPAWN`:
inspect the actual host and recover/bind the existing agent. Do not infer that a
crash happened before the call. If execution cannot be resolved, retain the token
and report the concrete blocker. `RECOVER_BOUND_AGENT` directs recovery of the
already bound identity. Never use `finish`, a new token, goal revision, or a new
state directory solely to replenish capacity retries. No automatic retry follows
budget exhaustion. Explicit execution reconciliation uses the base protocol and
must preserve this history. Source drift, pause, stop and required separate claims
review still apply; capacity failure never authorizes the worker to approve its
own claims or the parent to silently replace the delegated reviewer.

The same evidence and lifecycle rules apply outside controller mode: keep a
three-call maximum in the existing task history unless an explicit budget was
set, record uncertain calls, recover identities and require new capacity evidence
before retrying. This guidance does not install a runtime interceptor or change
the host's own thread limit.

## Optional executable host integration

For a host with an explicit trusted Python provider, use the [native coordinator](native-agent-coordinator.md). It executes result harvesting, bounded identity reuse and verified close attempts through that provider. It installs no background runner and cannot add a missing native close operation. The tool-driven protocol above remains valid.
