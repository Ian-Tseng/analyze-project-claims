# Long-running goal controller

Use the packaged [controller](../scripts/long_running_controller.py) for an
explicitly authorized finite goal. It persists work, reviews, holds, repair
attempts and budgets in a hash-linked append-only journal with a process lock.
It orchestrates existing authority; a manifest string cannot authorize work.
The active skill retains semantic review and formal evidence procedures.

For delegated execution, read [subagent mode](subagent-mode.md) and the
[host protocol](subagent-host-protocol.md). The [startup example](subagent-mode.md#synthetic-startup-example)
contains a complete synthetic configuration. Inline mode uses the same base
contract without `subagent_mode` or claim fields. Use Python 3.10 or later.
Local candidate validation used Windows and Python 3.12; compatibility across the
repository's remaining OS/Python matrix requires the corresponding CI results.

Apply [evidence-guided agents](evidence-guided-agents.md) to all participating
roles. Investigation targets need not be supported before work.

## Manifest and action contract

Required top-level fields are nonempty `goal_id`, `goal_revision`, `objective`,
`authorization_ref`, an existing `project_root`, nonempty project-relative
`evidence`, nonempty `success_criteria`, and nonempty `actions`.
`max_dispatches` is a finite integer from 1 through 10000 (default 100).
`max_repair_cycles` is an integer from 1 through 10000, defaulting to 32 for new
goals. Initialization persists it; `status.repair_cycle_limit` reports the effective
cap. Old journals without the field retain three, including after goal/plan
revision. No existing attempt is expanded by an upgrade. Review dispatches consume
`max_dispatches` too; that independent budget may stop a run earlier.
Declare all controlling protocols, implementation, configuration and finalized
output evidence. Missing files have a null hash and prevent goal completion.
Paths cannot escape the project or cross links. Keep state and generated
reports outside the source inventory. The controller cannot find unlisted sources.

Actions have unique stable `id` and nonempty `instruction`. `kind` is `work`,
`validate`, or `repair` (default `work`). Optional fields include acyclic
`depends_on`, `required` (default true), `requires_review` (default true),
`command` (an argv list), and `timeout_seconds` (1 through 86400; default 300).
A repair additionally needs `attempt_id` and `attempt_authorization_ref` and
always requires review. Subagent mode always requires review for every action.
Optional contingency actions set `required: false`.

Dependencies retain premises as well as execution order. A hold on an ancestor
blocks dependent work even after that ancestor finished. Actions are one-shot
units; do not rename them or start another state store to bypass history.
Reserve optional repairs under the same authorized attempt. Done, failed and
uncertain execution count toward its saved repair-cycle limit; `not_started`
does not. Repeated findings, unchanged/repeated candidate identities or reaching
the saved cap stop that attempt. The [review-learning rule](review-learning.md#repair-cycle-budget-and-adaptation)
allows evidence-based adjustments for future goals, not budget changes through
plan patches or new attempt IDs that evade an exhausted attempt. New sessions, clock changes and goal revisions do not reset it.

## Cooperative execution

The host retains one state directory and loops:

```text
init --config goal.json
next
check --token TOKEN
finish --token TOKEN --result result.json
next
```

Each command follows `<python-3> <skill-root>/scripts/long_running_controller.py
--state <state-directory>`. `next` persists a `DISPATCH` request before execution.
Call `check` immediately before action execution; proceed only on `READY`.
`STALE` requires fresh review: finish unstarted work as `not_started`, or record
the failed review for its exact existing token. Respect pause/stop. Checks cannot
lock an external producer; inspect finalized outputs before reviewing them.

A review is due initially, after each substantive work result, and when declared
evidence changes. Units should be meaningful milestones, not individual tool
calls. Continue eligible work after each routine result without asking for
another continuation instruction. `IN_FLIGHT` returns the existing request:
recover it, never dispatch a duplicate. `WAITING` identifies unresolved
prerequisites, not completion. Use finite waits or an already authorized host
continuation facility for external evidence.

Work results use `status`: `done`, `failed`, `uncertain`, or `not_started`, plus
observations, changed artifacts and limitations. Done is an execution outcome,
not scientific support. On unknown execution outcome, record uncertain for the
same token. Inspect actual operation state before using `reconcile --action ID
--outcome done|pending --evidence "actual observation"`; reconcile applies to
failed/uncertain actions and retains attempt history. Exact duplicate finishes
are idempotent; conflicting results are rejected.

`pause`, `resume`, and `stop` take `--reason` and require corresponding user
authority. Reviewers cannot issue them. Preserve the host's own goal-state rules.
`status` reports retained decisions. In subagent mode it also samples current
source/reviewer identities and exposes freshness separately from those decisions.
Saved reports describe their last sample, not continuous monitoring.

## Base review result

Every review binds both source and semantic request digests. Copy bindings
programmatically from the checked request; do not retag an old review.

```json
{
  "review_status": "COMPLETE",
  "decision": "CONTINUE",
  "snapshot_digest": "copy request.snapshot.digest",
  "request_digest": "copy request.semantic_digest",
  "coverage": "Actual locations inspected, reused evidence and limitations",
  "cleared_actions": ["square"],
  "next_action": "square",
  "holds": {},
  "findings": [],
  "goal_complete": false
}
```

Statuses are `COMPLETE`, `PARTIAL`, or `FAILED`. Decisions are `CONTINUE`,
`REPAIR`, `VALIDATE`, or `HOLD_DEPENDENT_ACTION`. Partial reviews clear only
checked premises; failed reviews clear nothing. Repair/validate decisions need
a matching preauthorized `next_action`. Only REPAIR can clear repair work.
A request's semantic digest binds goal revision, configuration, actions, holds,
findings and attempts; matching file hashes alone cannot validate an old review.

Persist holds as `holds: {"action-id": "reason and resumption condition"}`.
Release explicitly through `release_holds` with an evidence-backed reason and
clearance of that action. Findings each need `id`, `evidence` (stable locator),
and `reason`. Omission preserves them; close through `resolved_findings` with
an evidence-backed resolution. Stable finding identities preserve repair bounds.

Completion requires `goal_complete: true`, COMPLETE review, no open findings or
holds, all required actions done, all declared evidence present, no next action
or clearances, `verified_criteria` exactly covering configured success criteria,
and nonempty `evidence_refs`. Include the strongest safe claim, scientific and
acceptance boundaries and actual audit references. Structural validation does
not establish semantic support or replace formal evidence acceptance.

## Commands and goal changes

`revise --revision REV --objective TEXT --criterion TEXT --authority TEXT`
changes objective/revision/criteria only, without an in-flight token. It retains
actions, findings, holds, budgets and attempts and requires actual owner authority.

`authorize-plan --proposal FILE --scope existing|expanded --authority TEXT
--rationale TEXT` records coordinator authority for an exact proposal;
`revise-plan --proposal FILE` commits it to the same journal. A plan proposal
contains exactly `revision_id`, `base_config_digest`, `add_actions` (full new
action definitions), and `dependencies` (existing pending, never-executed action
IDs mapped to prerequisite lists). At least one addition or dependency change
is required. The revision ID must be unused and the base digest current.
These commands are separate from reviewer recommendations. They cannot
remove/rename actions, edit existing instructions, erase findings, release holds,
rewrite outcomes, replenish budgets or reset stopped attempts. Finish/reconcile
in-flight work before changing the plan. Expanded work needs its actual authority.

## Optional command runner

For separately authorized finite local commands, configure work `command` argv
lists and `reviewer_command`, then run `run --execute --watch-seconds 60`.
The runner supplies request JSON on stdin. Workers signal execution outcome by
exit code; reviewers must be read-only and emit one review JSON object on stdout.
Outputs are retained. Commands run without a shell. An adapter for subagent mode
must implement actual skill invocation and the full claim-update schema.

`--execute` does not grant authority. `--watch-seconds` bounds idle waiting from
runner invocation, not total execution; commands have their own timeouts.
Missing adapters return `NEEDS_AGENT` with the persisted request. Two failed
reviewer invocations leave dependent actions pending. Timeouts can leave child
processes or partial effects: retain uncertainty and inspect before retrying.

No scheduler, service, model client, host hook or background wake mechanism is
installed. A host ending requires another authorized invocation. Hashes detect
accidental corruption; they do not authenticate a user controlling the journal.
No automatic migration enables subagent mode on an existing base-mode journal.

For delegated execution, use the [completed-agent lifecycle check](subagent-host-protocol.md#check-completion-and-release-host-resources) after results and before new dispatch. The `agent-cleanup` command produces a conservative plan; actual host closure is capability-dependent and never deletes evidence or clears pending claims review.
