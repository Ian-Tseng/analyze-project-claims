# Claim-guided subagents

An authorized host can delegate one substantive work unit, invoke
`analyze-project-claims` on its outcome, update affected working claims and
regenerate dependent reports before continuing. Provisional hypotheses may guide
work; only declared execution prerequisites require current support. Negative
observations revise claims and dependent plans instead of being hidden. Failed and uncertain work also return to claims review.
This is sequential active-session orchestration; it does not install a scheduler
or wake a host after its process ends.

Use a host with native subagent creation, messages, waiting and recovery. The
Python helpers persist the protocol; they do not call a model. Delegate only
when the user or applicable instructions authorize both the work and delegation.
Read the [base controller contract](../skills/analyze-project-claims/references/long-running-mode.md),
[claim schema](../skills/analyze-project-claims/references/subagent-mode.md), and
[host protocol](../skills/analyze-project-claims/references/subagent-host-protocol.md).

## Start a bounded goal

Use the packaged [complete synthetic startup example](../skills/analyze-project-claims/references/subagent-mode.md#synthetic-startup-example).
It constructs the whole manifest, initializes one durable state directory, and
shows the native `next -> check -> spawn-attempt -> check -> spawn waiting agent -> bind-agent -> check ->
START -> wait/recover -> finish -> next` sequence. Supply actual delegation
authority and resolve the active installed skill before initialization.

## Read results and recover

```text
python3 skills/analyze-project-claims/scripts/long_running_controller.py --state claims-demo/state status
```

Read `claims-demo/state/reports/current.json` for the report revision and its
file hashes. The referenced `claims.json` and `progress.md` project reviewed
working claims, evidence links, limitations, dependencies and pending review.
`freshness` distinguishes CURRENT, STALE and UNKNOWN sampled identity from
historical decisions. Historical `complete` can remain true while
`freshness.completion_current` is false. CURRENT identity does not itself
resolve pending review. Reports are snapshots, so sample status again before
relying on freshness.

On `IN_FLIGHT`, recover the returned token and top-level `delegation`; do not
spawn another worker. Resolve actual agent/process state before retrying unknown
work. Preserve pauses, holds, attempt limits and finite dispatch budgets.
Generated reports and journal files cannot be their own source evidence.
Operational working claims do not accept a formal component map: substantive
formal scans retain the skill's verification, reconciliation, audit records and
human acceptance requirements.

## Verification boundary

The precursor local installation completed a bounded native worker/reviewer
fixture. Fresh native activation of this packaged port remains untested.
Repository regressions and startup checks support only their tested cases;
neither the example nor source provenance establishes semantic review accuracy,
scientific benefit, unattended recovery or a performance improvement.
The [source log](../skills/analyze-project-claims/references/subagent-design-sources.md)
separates design guidance, local choices and AI Scientist-derived review provenance.

New goals persist `max_repair_cycles` (default 32); existing journals without the
field keep their three-cycle limit. Recorded repeated progressing cap hits may
justify a prospective +16 adjustment under the
[review-learning policy](../skills/analyze-project-claims/references/review-learning.md#repair-cycle-budget-and-adaptation).

Use the [completed-agent lifecycle check](../skills/analyze-project-claims/references/subagent-host-protocol.md#check-completion-and-release-host-resources) after results and before new dispatch. The `agent-cleanup` command produces a conservative plan; actual host closure is capability-dependent and never deletes evidence or clears pending claims review.

For `agent thread limit reached`, use [bounded spawn recovery](../skills/analyze-project-claims/references/subagent-host-protocol.md#recover-agent-thread-limit-reached).
`spawn-attempt` and `spawn-result` journal up to `max_spawn_attempts` calls per
token (default 3, including the initial call). Retry only after a confirmed
non-creation rejection and new capacity evidence. Uncertain calls require identity
recovery; the pending token, work budgets and separate claims review remain.
