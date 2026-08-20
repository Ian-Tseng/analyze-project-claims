---
name: analyze-project-claims
description: Analyze a project as a connected system of objectives, claims, assumptions, evidence, counterevidence, dependencies, risks, lifecycle states, and decisions. Use when assessing project health or direction; checking inconsistencies; interpreting a product-lifecycle verification receipt or bounded skill-quality receipt; auditing research evidence, experiment status, completion markers, paper-table eligibility, RAG transition artifacts, leakage, split integrity, manifest consumption, or claim boundaries; deciding whether to continue, validate, redesign, pause, or stop; or repairing active claims without rewriting historical evidence.
license: MIT
---

# Analyze Project Claims

Produce an evidence-bounded account of what the project claims, what the
evidence establishes, where inconsistencies remain, and what action should
come next.

## Select the analysis depth

Use the lightest sufficient mode:

- **Quick audit:** conclusion, critical conflict, bottleneck, and next action.
- **Research audit:** add protocol boundaries, counterevidence,
  reproducibility, and claim-to-evidence matching.
- **Full strategic audit:** add alternatives, dependencies, risks, stop
  conditions, and reversal triggers.

## Establish authority and scope

Before judging a claim:

1. Identify the question and success condition.
2. Locate authoritative configurations, protocols, artifacts, code, tables,
   and logs.
3. Separate active sources of truth from drafts, generated summaries,
   archives, and failed attempts.
4. Identify immutable historical evidence that must not be rewritten.
5. Treat missing evidence as unknown, not false.

For research claims, trace:

```text
dataset/source
-> partition and label exposure
-> fitted or fixed component
-> produced output
-> evaluation metric
-> claim boundary
```

## Classify claims

Decompose compound statements into atomic claims. Use these statuses:

- **supported:** direct evidence matches the stated scope;
- **partially supported:** direct evidence exists with material limitations;
- **contradicted:** same-scope counterevidence conflicts with the claim;
- **untested:** no direct test exists;
- **invalidly specified:** the population, protocol, metric, comparator, or
  state definition is incomplete.

Do not average away a direct falsifier. Repeated folds, seeds, or rows from one
source are not independent replications.

## Keep state dimensions separate

Do not flatten workflow, evidence, evaluation, and acceptance into one status.
A run may simultaneously have:

```text
runner_stage = complete
audit = failed
scientific_evaluation = negative
paper_acceptance = not_eligible
```

Use at least these dimensions when applicable:

- **artifact state:** missing, partial, ready, corrupt;
- **runner state:** planned, running, interrupted, complete;
- **audit state:** not_run, passed, failed;
- **scientific state:** untested, supported, failed_gate;
- **acceptance state:** eligible, not_eligible, rejected.

## Audit inconsistencies

Check:

- **definition:** one term has multiple meanings;
- **type or flow:** a component receives or produces a different object than
  claimed;
- **scope:** narrow evidence is used for a broader claim;
- **claim-evidence:** the cited artifact does not directly test the claim;
- **goal-metric:** a metric improves while the intended outcome fails;
- **lifecycle:** runner, audit, completion, or acceptance states are conflated;
- **monitor:** file existence is mistaken for successful validation;
- **document:** prose, formulas, configurations, code, tables, and artifacts
  disagree;
- **provenance:** an artifact exists without evidence that the reported
  pipeline consumed it.

For each finding report the conflicting elements, why they conflict, the
safest interpretation, and the evidence or repair needed.

## Enforce completion and independence boundaries

Treat accepted experiment completion as an explicit AND gate:

```text
accepted_complete =
    valid_runner_completion
    AND audit_report.audit_passed == true
    AND valid_audit_completion_marker
    AND required_artifacts_open_and_validate
```

Artifact existence is not a pass. A runner marker proves only runner-stage
completion unless the contract includes audit acceptance. Preserve failed and
superseded attempts.

Use precise audit language:

- **separate audit invocation:** separate run, possibly shared production code;
- **deterministic replay:** same frozen implementation recomputes outputs;
- **independent structural audit:** separate checks of schemas, hashes,
  cardinality, operators, or manifests;
- **independent implementation:** separate scientific calculation code;
- **independent scientific replication:** independently collected or evaluated
  evidence.

Shared-code replay can detect corruption but not every shared implementation
error.

## Apply specialized research rules

For finite-state operators, transition authorization, logic-guided RAG,
leakage, split consumption, and paper-table eligibility, read
`references/logic-guided-rag-audit.md`.

Keep structural and scientific gates separate. An operator, artifact, leakage,
or lifecycle pass does not prove scientific benefit or deployment readiness.

## Bound validation and publication claims

Keep packaging, behavior, scientific, reliability, and publication claims
separate:

- a structural validator proves well-formed packaging only;
- deterministic regression tests prove only tested invariants and fixtures;
- success on one project does not prove general reliability;
- paper-table eligibility differs from publication potential of the method.

State the evaluated cases, test scope, counterevidence, and additional evidence
required for any broader claim.

## Repair authorized inconsistencies

When repairs are authorized:

1. Add a deterministic regression test and confirm the intended failure.
2. Repair the active interpretation, monitor, table, or implementation.
3. Preserve source-hashed protocols and historical artifacts unless a new
   scientific identity is intentionally created.
4. Update every coupled active surface.
5. Re-run tests, preflight, monitors, and stale-language scans.
6. Iterate until no active same-scope inconsistency remains.

A result-changing protocol or implementation edit requires a new scientific
configuration hash and run group.

## Recommend and return

Prefer the smallest action that tests a critical uncertainty, produces an
observable signal, preserves options, fits available authority, and prevents a
false claim. State the success signal, failure signal, evidence produced, and
reversal condition.

Return:

1. overall conclusion;
2. compact inconsistency table;
3. strongest safe claim;
4. scientific and acceptance boundary;
5. recommended repair or next experiment;
6. unresolved uncertainty.

Use:

```text
finding | evidence | status | safest interpretation | required repair
```

## Interpret lifecycle receipts

When given a `LifecycleVerificationReceipt`, read
`references/lifecycle-verification-receipt.md`. Do not execute lifecycle
operations here. `product-lifecycle` owns execution; this skill validates and
interprets the receipt with `scripts/lifecycle_receipt.py`.

Keep check status, claim status, and evidence method separate. A `COMPLETE`
receipt supports only its exact product, release, adapter, target, platform,
phase, and evidence scope.

At most one digest-bound read-only follow-up request may be produced per
receipt. Stop on a repeated finding/evidence requirement and after three
distinct reconciliation cycles. A follow-up request never authorizes
publication, mutation, reporting, cleanup, or recursive skill execution.

## Reconcile the component map

Every substantive formal audit first verifies the bundled evidence engine:

```text
<python-3> scripts/reconcile_component_map.py verify-self
```

Then reconcile a deterministic observation:

```text
<python-3> scripts/reconcile_component_map.py reconcile \
  --observation <observation.json> \
  --map-root <map-root> \
  --project-root <project-root>
```

Read `references/component-evidence-protocol.md` before authoring an
observation, reviewing a candidate, or accepting a map.

The accepted map is current structural authority. Candidates, deltas, and
history are immutable evidence. Discovery never implies acceptance. Preserve
the accepted map while a candidate is pending. Only the relevant human
authority may accept the exact reviewed candidate:

```text
<python-3> scripts/reconcile_component_map.py accept \
  --candidate <candidate.json> \
  --map-root <map-root>
```

Test-backed elements must map the test and direct implementation, schema,
template, configuration, or prompt dependencies. Ordinary file drift matters;
generated Python bytecode caches do not.

For read-only work, return the proposed observation and delta without claiming
that they were persisted or accepted.

## Emit an evidence-bound audit record

Every substantive project scan yields one record after map reconciliation,
including scans that are clean, partial, failed, or blocked. For formal work,
use v2 and read `references/evidence-bound-audit-records.md`.

The record separates:

- stable claims bound to accepted component and element IDs;
- exact evidence items with locators, methods, observations, and digests;
- explicit support, contradiction, limitation, and context edges;
- named limitations linked to claims and evidence.

Use staged commands:

```text
<python-3> scripts/record_scan.py preflight --map-root <map-root> --project-root <root>
<python-3> scripts/record_scan.py init --map-root <map-root> --project-root <root> --output <draft.json>
<python-3> scripts/record_scan.py evidence digest --source <path> --locator <typed-locator> --project-root <root> --id <evidence-id>
<python-3> scripts/record_scan.py validate --record <input.json> --map-root <map-root> --project-root <root>
<python-3> scripts/record_scan.py append --record <input.json> --map-root <map-root> --project-root <root> --log-dir <history> --report-dir <reports>
<python-3> scripts/record_scan.py verify --record <record.json> --map-root <map-root> --project-root <root> --report <report.md>
```

`executed_test` cites persisted output, not test source. `not_tested` is
context-only. External sources are never fetched implicitly. Markdown is a
derived view, not a second authority. Never imply that a read-only proposal
was appended.

## Consume bounded skill-quality receipts

When a compatible Ian-Tseng-managed skill ends with an exact
`SkillOutcomeReceipt` marker, or the user asks to inspect pending skill
quality, read `references/skill-quality-loop.md`.

The receipt is producer-declared and content-free. A non-`no_issue` signal
paired with `analyze_quality` can create one local proposal. `no_issue`
paired with `none` is a no-op. Neither can prove producer identity or
authorize edits, reports, issues, updates, release, or publication. Never
inspect transcripts or project content as a fallback.

Portable explicit use:

```text
<python-3> scripts/skill_quality_loop.py --format json doctor
<python-3> scripts/skill_quality_loop.py --format json consume --marker <marker>
<python-3> scripts/skill_quality_loop.py --format json consume
<python-3> scripts/skill_quality_loop.py --format json proposal-show --proposal-id <id>
```

The optional Codex plugin hook requests at most one continuation for a valid
original turn. It cannot guarantee that this skill is invoked, and another
hook may veto continuation. Failure leaves the substantive result intact and
the persisted receipt available for explicit consumption.

Contribution is always separate and consent-gated. Preview sends nothing.
Public submission requires approval of the exact draft and a second
draft-specific public-issue confirmation. Approval expires after 24 hours and
one contribution ID may create at most one issue. On an unknown GitHub outcome,
reconcile the contribution ID before retrying. Only `Ian-Tseng` may add
`agent-ready`; that permits one isolated map-pending candidate, never map
acceptance, merge, release, issue closure, or installed update.

## Report internal product failures separately

Problem reporting applies only when this skill, a packaged helper, or its
managed updater fails internally. Project contradictions and defects are audit
results and must never be transmitted as product reports.

Finish the substantive audit first. Use only
`scripts/problem_report.py` fixed enums and bounded generic fields. Never
include project text, paths, raw logs, prompts, attachments, environment
variables, tokens, credentials, identity, or arbitrary metadata.

The default is local and unconfigured. Show the exact preview and require
exact consent before submitting. A public GitHub issue requires a second,
report-specific confirmation. Security vulnerabilities use private
vulnerability reporting. Reporting failure must not replace or shorten the
audit. See the script help and `references/problem-report.schema.json` for the
closed contract.

## Keep analytics separate

Installation analytics are optional owner infrastructure, never a default
side effect. Do not create identity or send events on install, invocation,
update, or problem reporting. Explicit opt-in, endpoint configuration, and a
later check-in are separate actions. Update or reporting consent does not
authorize analytics. Update consent and reporting consent do not authorize
analytics.

Route explicit requests to `scripts/installation_analytics.py`. Describe any
owner aggregate as unique consenting activated installations: never downloads, users, or total installs.
Do not claim a live count without an observed deployed endpoint.

## Run consent-gated update maintenance

After the substantive result and immediately before the final response, run:

```text
<python-3> <skill-root>/scripts/update_policy.py --format json maintain
```

This applies only to a standalone GitHub-CLI-managed installation. Maintenance
failure never replaces the analysis. Append its `message` and `action` only
when `emit` is true. A replacement activates on the next invocation.

Route explicit requests:

- enable automatic updates -> `enable --mode auto`;
- notify about updates -> `enable --mode notify`;
- disable updates -> `disable`;
- show status -> `status`;
- diagnose ownership -> `doctor`;
- check now -> `check-now`.

Plugin-hosted, manual, project-scope, pinned, duplicated, or locally edited
copies are never blindly replaced. `doctor` shows every same-name visible copy
and the running copy. A GitHub CLI authority claim additionally requires exact
source, path, version, tree, scope, pin, and package-manifest verification.
Keep one explicit update authority; never remove a copy automatically.

## Guardrails

- Lead with evidence, not advocacy.
- Preserve same-scope counterevidence.
- Do not treat artifact existence as artifact use.
- Do not treat audit invocation as independent implementation.
- Do not treat workflow completion as scientific success.
- Do not treat a receipt as producer authentication or update authority.
- Do not treat one dataset or task as proof of general RAG performance.
- Do not rewrite historical evidence to make a project appear consistent.
- Keep `unknown`, `failed`, `not_eligible`, and `not_proved` distinct.
