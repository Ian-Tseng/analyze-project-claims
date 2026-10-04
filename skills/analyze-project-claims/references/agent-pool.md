# Concurrent claim-guided agents

Use this opt-in contract for a new goal whose independent work can run concurrently.
The default controller remains serialized. Existing journals retain their mode;
there is no automatic migration or permission to replace an unfinished goal.
Read the base [controller](long-running-mode.md), [claims](subagent-mode.md) and
[native host](subagent-host-protocol.md) contracts first. Pool rules below specialize
scheduling and evidence scope; they retain authority, evidence acceptance and
finite work/retry budgets.

## Declare independent work

Add `"agent_pool": {"max_workers": 2}` at the top level of a new controller
manifest that also enables `subagent_mode`.
`max_workers` is an integer from 1 through 32. Every action declares
`read_paths` and `write_paths`, lists of exact project-relative
files from the manifest's `evidence` inventory. Include all actual inputs and
outputs. Shared read-only inputs are allowed. Conflicting writes, a writer and
reader of the same path, and conflicting claim dependencies prevent overlap.
Path aliases and links must not conceal a conflict. These are cooperative access
contracts, not an operating-system sandbox; the host still enforces write scope.

For example, two actions can read `protocol.txt` while writing separate
`a.json` and `b.json`. An integration action reading both outputs depends on
both producers and waits for their required claims reviews. Claim prerequisites
remain distinct from hypotheses under investigation.

The host needs capacity for the configured workers and a separate reviewer.
Do not infer host thread capacity from `max_workers`, assume completed threads
were released, or substitute interruption for a missing close operation.
Reserve role-compatible reviewer capacity and reuse known idle agents safely.

## Inspect, reserve, run and refill

The coordinator owns the shared journal. Use `status` or `next` without a dispatch
ID to inspect outstanding assignments. A pool scheduling intent needs a unique,
durable ID:

```text
python3 scripts/long_running_controller.py --state STATE next --dispatch-id INTENT
```

Keep that intent ID through lost responses and recovery. Repeating it recovers
its assignment instead of reserving duplicate work. New scheduling intents may
reserve independent work while another worker runs. Never execute a request
again merely because an old intent returns it; check its current token/result.

For each new request, retain its complete token, role, evidence scope, claims,
dependencies, limits and reviewer bindings. Perform `check` immediately before
starting. Use the existing bounded `spawn-attempt` / `spawn-result` protocol for
new native agents and bind the actual returned identity before releasing it to
start. The Python controller does not call a model, inspect native host status,
or install an unattended wake mechanism.

At startup/recovery, after a result, before dispatch and before waiting, inspect
all owned native agents. Harvest each finished assignment promptly, verify its
identity and execution outcome, persist the result, and call `finish` with that
exact token. Idle status or a message alone does not prove child operations ended.
Keep uncertain outcomes unresolved until actual execution evidence is available.

Continue the scheduling loop after each recorded result. Dispatch required reviews
and independent ready work as permitted; do not wait for all workers in a batch.
Dependent tasks wait for the producer's review. Keep useful work on the goal's
dependency chain moving without manufacturing tasks to occupy agents.

## Reuse a finished agent

Use `bind-agent --token TOKEN --agent-id ID --observation FILE` for an already
owned identity. Supply a fresh actual host observation and record where it came
from; the prior result and resolved execution must already be recorded.
Do not reuse an identity that still owns another in-flight token. The observation
has exactly `observed_at` (current Unix seconds), `source_ref`, `agent_id`, `status`
(idle, completed, failed or cancelled), and `execution_quiescent: true`.
It must be at most 60 seconds old and cannot be future-dated.

Bind the new assignment before delivering its start message. On hosts exposing
`collaboration`, `followup_task` starts a finished/idle agent's new turn;
`send_message` alone does not. Include fresh task context instead of relying on
the old conversation. If delivery has an ambiguous outcome, inspect the existing
binding and native task before retrying. When the host returns an actual start/wake
acknowledgement, record it with `start-agent --token TOKEN --agent-id ID
--source-ref RECEIPT`; this records an observation and does not launch an agent.
A missing acknowledgement remains a recovery condition, not a reason to send the
assignment twice. A later actual result also establishes that execution occurred.
A new token is not permission to replay
an unresolved old assignment.

A reviewer must have a different identity from the worker whose output it reviews.
This restriction persists across agent reuse and coordinator restart. A dedicated
reviewer is a useful arrangement; it remains subject to current evidence and
freshness checks. Human component-map acceptance is never delegated to it.

## Claims, snapshots and completion

Workers have scoped evidence bindings. A change to a disjoint worker's declared
output need not invalidate their inputs. A change outside declared write ownership,
a reviewer-source change or an actual prerequisite change still requires review.
Declarations do not prove that an output is valid or that a scientific claim holds.

Each substantive outcome retains its own review obligation. Reviews are serialized
and bind the exact work results, evidence and claim state they assess. A review
cannot erase a newer unresolved outcome or clear claims outside its bound scope.
A worker's `done` result is operational completion; dependent execution needs the
required review as well. Negative evidence can finish an investigation without
establishing the hypothesis.

Initial review, global evidence/contract changes and final goal review may require
a global barrier. A scoped intermediate review cannot declare the whole goal
complete. Final completion requires no active assignments, no unresolved review
obligations, all required actions completed, current evidence and the existing
full success-criteria review. Preserve holds, findings, counterevidence and budgets.
Pool mode does not silently expand a legacy repair limit.

The initial implementation conservatively locks the affected claim dependency
closure: branches that share a downstream dependent claim may serialize even when
their files differ. Preserve real claim relationships instead of removing them to
force concurrency. The serial `run` command rejects pool configurations; use an
explicit concurrent native host or subprocess adapter.

## Observe progress and measure benefit

Record native agent status and task status separately. Track completed and reviewed
outputs, outstanding obligations, dependency/capacity holds, dispatch latency and
real worker overlap. An empty ready queue is a waiting condition unless the goal's
completion checks passed. Prefer event notifications and bounded waits of at most
60 seconds on hosts that need regular user progress updates.

A benchmark must compare equal work, output checks, review requirements and resource
limits. Include dispatch, subprocess startup, actual computation, review, journal
integration and final acceptance in end-to-end timing. Preserve raw events and
source identities. The repository's `evaluation/agent-pool` pilot uses deterministic
CPU subprocess work and a synthetic reviewer adapter; it does not establish native
AI review accuracy, scientific benefit or general project acceleration.

No performance threshold belongs in ordinary functional CI. Report measured
outcomes, including regressions or inconclusive timing, within their workload and
machine scope. Do not promote more completed task IDs into a speed claim.
