---
name: analyze-project-claims
description: Analyze a project as a connected system of objectives, claims, assumptions, evidence, counterevidence, dependencies, risks, lifecycle states, and decisions. Use when assessing project health or direction; checking inconsistencies; interpreting a product-lifecycle verification receipt; auditing research evidence, experiment status, completion markers, paper-table eligibility, RAG transition artifacts, leakage, split integrity, manifest consumption, or claim boundaries; deciding whether to continue, validate, redesign, pause, or stop; or repairing active claims without rewriting historical evidence.
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

Decompose compound statements into atomic claims.

Use these evidence statuses:

- **supported:** direct evidence matches the stated scope;
- **partially supported:** direct evidence exists but has material limitations;
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

These values are not contradictory because they belong to different
dimensions.

Use at least these dimensions when applicable:

- **artifact state:** missing, partial, ready, corrupt;
- **runner state:** planned, running, interrupted, complete;
- **audit state:** not_run, passed, failed;
- **scientific state:** untested, supported, failed_gate;
- **acceptance state:** eligible, not_eligible, rejected.

## Audit inconsistencies

Check these classes:

- **definition:** one term has multiple meanings;
- **type or flow:** a component receives or produces a different object than
  claimed;
- **scope:** narrow evidence is used for a broader population, dataset, task,
  or deployment claim;
- **claim-evidence:** the cited artifact does not directly test the claim;
- **goal-metric:** a metric can improve while the intended outcome fails;
- **lifecycle:** runner, audit, completion, or acceptance states are conflated;
- **monitor:** file existence is mistaken for successful validation;
- **document:** prose, tables, formulas, configurations, code, and artifacts
  disagree;
- **provenance:** an artifact exists but there is no evidence that the reported
  pipeline consumed it.

For every finding report:

1. conflicting elements;
2. why they conflict;
3. safest current interpretation;
4. evidence or repair needed to resolve it.

## Enforce lifecycle completion gates

Treat accepted experiment completion as an explicit AND gate.

A typical accepted-completion contract is:

```text
accepted_complete =
    valid_runner_completion
    AND audit_report.audit_passed == true
    AND valid_audit_completion_marker
    AND required_artifacts_open_and_validate
```

Important rules:

- `audit_report.json` existing does not mean the audit passed.
- A runner completion marker proves only runner-stage completion unless the
  contract explicitly includes audit acceptance.
- A failed audit report must never make an audit view `READY`.
- Monitors should require a success marker or validate report content.
- Preserve failed attempts and their counterevidence.
- Do not relabel a failed or superseded run as corrected.

If a legacy file is named `experiment_complete.json` but is written before
audit, describe it as a legacy runner-stage marker. Do not rewrite historical
artifacts merely to improve naming.

## Distinguish audit independence

Use precise terminology:

- **separate audit invocation:** audit runs separately but may reuse production
  functions;
- **deterministic replay:** stored outputs are recomputed from the same frozen
  implementation;
- **independent structural audit:** a separate code path checks schemas,
  hashes, cardinality, operators, or manifests;
- **independent implementation:** the scientific calculations are implemented
  separately;
- **independent scientific replication:** new evidence is collected or
  evaluated independently.

Do not call a replay an independent implementation when runner and auditor
import the same fitting, metric, or decision functions.

A shared-code replay can detect corruption and artifact mismatch, but it cannot
detect every shared implementation error.

## Apply formal operator definitions

Define the finite domain before applying operators.

For a finite state domain $D$:

\[
\neg A = D \setminus A,
\qquad
A \land B = A \cap B,
\qquad
A \lor B = A \cup B.
\]

For a current singleton state $s$:

\[
\operatorname{NOT}(s)=D\setminus\{s\}.
\]

If

\[
D=\{\mathrm{SUPPORT},\mathrm{CONTRADICT},\mathrm{NOINFO}\},
\]

then every current state has exactly two complement candidates.

Describe this as:

> an exact two-candidate complement over the three-state label domain

Do not call it a "two-state complement," because the domain contains three
states.

Candidate generation does not imply transition execution. Record candidate
enumeration, authorization, execution, and evaluation as separate stages.

## Audit logic-guided RAG evidence

Require this flow:

```text
dataset/source
-> partition and label exposure
-> initial label and score state
-> exact complement candidates
-> fitted or fixed authorization rule
-> predicted transition or abstention
-> evaluation metrics
-> claim boundary
```

Check:

- the declared label domain;
- exact complement coverage;
- separate error and abstention states;
- unique record keys and cardinality;
- finite feature values and probabilities;
- prohibited feature names and feature construction;
- train/test example isolation;
- target-family exclusion from blocked training;
- candidate-pair preservation;
- actual trainer-consumed split manifest;
- manifest hash binding in predictions and lifecycle artifacts;
- scientific and acceptance flags.

Fold definitions or regenerated splits do not prove what a historical trainer
consumed. Exact-consumption claims require a persisted, pre-fit manifest or
equivalent direct evidence.

## Separate structural and scientific conclusions

Keep these gates distinct:

| Layer | What a pass establishes |
|---|---|
| Operator | Implementation matches the declared finite-state relation |
| Artifact | Stored records are internally well formed |
| Leakage | Declared feature and split boundaries are implemented |
| Lifecycle | Required artifacts and success markers are present |
| Scientific | The named performance gates pass in the evaluated scope |
| Acceptance | A bounded paper-table or deployment action is permitted |

Never infer scientific benefit from a structural or lifecycle pass.

A result can correctly be:

```text
operator = valid
artifact_audit = passed
lifecycle = complete
scientific_gate = failed
paper_table_eligible = false
general_performance_proved = false
```

## Bound validation and publication claims

Keep packaging, behavior, scientific, reliability, and publication claims
separate:

- A structural skill-validator pass establishes well-formed packaging only.
- Passing deterministic regression tests establishes only the tested
  invariants and fixtures.
- Evidence that a skill helped on one project does not establish general reliability
  across projects, agents, models, or domains.
- The paper-table eligibility of an audited result is distinct from the
  publication potential of the auditing method itself.

When reporting status, state the evaluated cases, validator or test scope,
known counterevidence, and the additional evidence required for a broader claim.

## Repair authorized inconsistencies

When repairs are authorized:

1. Add a deterministic regression test for the inconsistency.
2. Confirm the test fails for the intended reason.
3. Repair the active interpretation, monitor, table, or implementation.
4. Preserve source-hashed protocols and historical run artifacts unless a new
   scientific identity is intentionally created.
5. Update every coupled active surface:
   - monitor configuration;
   - architecture/status document;
   - results document;
   - check table;
   - experiment log;
   - recorded document hashes;
   - regression tests.
6. Re-run tests, preflight, monitor snapshots, and stale-language scans.
7. Iterate until no active same-scope inconsistency remains.

A result-changing protocol or implementation edit requires a new scientific
configuration hash and run group.

## Recommend the next action

Prefer the smallest action that:

1. tests a critical uncertain claim;
2. produces a quick observable signal;
3. preserves future options;
4. fits available authority and resources;
5. prevents a false scientific or acceptance claim.

State the success signal, failure signal, evidence produced, and condition that
would reverse the recommendation.

## Return format

For an inconsistency or research audit, return:

1. overall conclusion;
2. compact inconsistency table;
3. strongest safe claim;
4. scientific and paper-acceptance boundary;
5. recommended repair or next experiment;
6. unresolved uncertainty.

Use a table with:

```text
finding | evidence | status | safest interpretation | required repair
```

## Interpret lifecycle verification evidence

Select this route automatically when the user provides a
`LifecycleVerificationReceipt` or asks whether product install, update,
activation, report-preview, rollback, and cleanup evidence is mutually
consistent. Do not run lifecycle commands here. `product-lifecycle` owns
execution; this skill only validates and interprets its receipt.

Use the installed, read-only consumer:

```text
<python-3> <skill-root>/scripts/lifecycle_receipt.py --format json interpret \
  --receipt <lifecycle-verification-receipt.json> \
  [--prior-request <verification-followup-request.json>]
```

Keep check status, claim status, and evidence method separate. Never collapse
the result into a bare `E2E PASS`. A `COMPLETE` receipt supports only its exact
product, release, adapter, target, platform, phase, and evidence scope.

If the result is `INCONSISTENT` or `EVIDENCE_GAP`, the consumer may emit one
digest-bound `VerificationFollowupRequest` whose only allowed action is a new
read-only plan:

```text
<python-3> <skill-root>/scripts/lifecycle_receipt.py --format json followup \
  --receipt <lifecycle-verification-receipt.json> \
  [--prior-request <earlier-followup-request.json>]
```

Do not recursively invoke another skill or interpret the request as approval
to execute, publish, report, mutate a live installation, or clean up. Stop
when the same finding/evidence requirement repeats, and stop after at most
three distinct reconciliation cycles. Return `RECONCILIATION_STALLED` with a
human decision point instead of looping.
## Build or reconcile the component-to-element map

At the start of every substantive audit, verify the versioned component-
evidence engine bundled inside this skill:

```powershell
py scripts/reconcile_component_map.py verify-self
```

This is a local, network-free identity check and must not invoke semantic
analysis recursively. The engine is part of the analyzer package, not a second
skill to discover or install. If verification fails, do not claim structural
evidence is verified; preserve any safe audit result, state the limitation, and
route only the fixed internal failure through the separate reporting policy.

Before a formal scan, reconcile the project structure against a durable
component-to-element map. The map records what can be checked; the scan record
records what was checked and what the evidence established.

Use this lifecycle:

1. Create a deterministic observation of the scoped components, elements,
   relations, source paths, and evidence locators.
   For a test-backed element, map both the test and every direct
   implementation, schema, template, configuration, or prompt dependency it
   exercises. Reject test-only evidence so source drift cannot be hidden by an
   unchanged test file.
   Directory source hashes include ordinary files but exclude only generated
   Python `__pycache__` content, `*.pyc`, and `*.pyo`, so interpreter cache
   creation cannot manufacture source drift.
2. If no accepted map exists, create a `bootstrapped_provisional` candidate.
   Discovery is not acceptance, so do not create an accepted map implicitly.
3. If an accepted map exists, compare identifiers, targets, relations, and
   source hashes:
   - no change: append a `checked_unchanged` history event and reuse the map;
   - structural or source change: emit a `drift_candidate` and delta;
   - same identifier with a changed meaning or target: emit a
     `conflict_candidate` and delta.
4. Preserve the accepted map while a candidate is pending. Never silently
   merge, rebuild, or overwrite it.
5. Accept a candidate only after the relevant authority and validation gates
   approve it. Archive the prior accepted map and record the acceptance event.

Use stable paths under a chosen map root:

```text
accepted-map.json       current accepted structure
accepted-history/       superseded accepted maps
candidates/             provisional, drift, conflict, or recovery candidates
deltas/                 machine-readable comparisons with the accepted map
scan-history/           append-only reconciliation events
```

Run reconciliation before logging the scan:

```powershell
py scripts/reconcile_component_map.py reconcile `
  --observation component-map-observation.json `
  --map-root .claim-audit/component-map `
  --project-root .
```

After an authorized review, accept the exact candidate returned by that
command:

```powershell
py scripts/reconcile_component_map.py accept `
  --candidate .claim-audit/component-map/candidates/<candidate>.json `
  --map-root .claim-audit/component-map
```

Use `references/component-map-observation.schema.json` as the reconcile-input
contract and `assets/component-map-observation.template.json` as its starting
shape. Observation elements use `evidence`; reject the generated-map field
`evidence_locators` as input rather than silently dropping it.

Use `references/component-map.schema.json` as the generated and promoted map
contract. `assets/component-map.template.json` illustrates generated output;
it is not a promotable candidate. Before acceptance, fail closed unless the
candidate satisfies the complete map structure, integrity hash, semantic map
identifier, active skill hash, and mapper version.

The accepted map is the current structural authority; candidates, deltas, and
history events are immutable evidence. If writes are not authorized, return
the proposed map and delta in the response without implying they were
persisted or accepted.

## Emit an evidence-bound audit record

Every substantive project scan must yield one audit record after map
reconciliation, including scans that find no inconsistency and scans that end
partial, failed, or blocked. For formal or explicitly logged work, use scan
record v2. It binds each material claim to exact evidence instead of treating a
file path or free-form evidence paragraph as support.

Start from `assets/scan-record-v2.template.json`; validate inputs against
`references/scan-record-v2.schema.json`. The append command persists the
normalized `references/scan-record-output-v2.schema.json` contract and can also
create a deterministic Markdown report. Read
`references/evidence-bound-audit-records.md` for the full authoring, migration,
error, and verification contract.

A v2 record has four normalized registries:

- `claims`: stable claim IDs, accepted `{component_id, element_id}` references,
  materiality, status, and rationale;
- `evidence_items`: exact local root-relative sources or declared immutable
  HTTPS sources, typed locators, methods, observations, and computed digests;
- `bindings`: explicit `supports`, `contradicts`, `limits`, or `context` edges;
- `limitations`: named boundaries linked back to claims and evidence.

Use the evidence methods `inspected`, `schema_validated`, `executed_test`,
`replayed`, `inferred`, or `not_tested`. `not_tested` is context-only and cannot
support, contradict, or limit a claim. `executed_test` must cite a persisted
result, log, or receipt; test source code is context, not execution evidence.
No command infers semantic entailment from matching prose. A supported claim
needs a support binding, partial support needs a named limitation, unresolved
counterevidence prevents a fully supported strongest claim, and stale or
unverifiable evidence cannot support the strongest-safe-claim summary.

Use the staged workflow so errors are found before an append-only write:

```text
<python-3> scripts/record_scan.py preflight --map-root <map-root> --project-root <root>
<python-3> scripts/record_scan.py init --map-root <map-root> --project-root <root> --output <draft.json>
<python-3> scripts/record_scan.py evidence digest --source <path> --locator <typed-locator> --project-root <root> --id <evidence-id>
<python-3> scripts/record_scan.py validate --record <input.json> --map-root <map-root> --project-root <root>
<python-3> scripts/record_scan.py append --record <input.json> --map-root <map-root> --project-root <root> --log-dir <history> --report-dir <reports>
<python-3> scripts/record_scan.py render --record <record.json> --output <report.md> --project-root <root>
<python-3> scripts/record_scan.py verify --record <record.json> --map-root <map-root> --project-root <root> --report <report.md>
```

`render` derives Markdown deterministically from a persisted record. `verify`
recomputes current local identities and reports drift without rewriting
history. External sources are never fetched implicitly; without a SHA-256 digest or a
full lowercase 40-/64-hexadecimal object ID they remain `unverifiable`. Reject path escapes, links or
reparse points, oversized selections, unstable reads, unsafe URLs, and
secret-like observation text before writing.

Legacy flag-only v1 records and `references/scan-record.schema.json` remain
readable but frozen. Render and verify label them `legacy_unbound` because their
prose cannot be upgraded into claim-to-evidence bindings automatically;
`draft-v2` copies it only into an untested, unbound draft for human review.

The accepted map is structural authority, the append-only JSON is audit
authority, and Markdown is a derived view. For a read-only task without write
authority, emit the complete proposed input in the response and say that it was
not persisted; never imply an append occurred.

## Report internal product failures separately

Problem reporting applies only when this skill, one of its packaged helpers,
or its managed updater fails internally. A contradiction, risk, failed
experiment, or defect found in the user's project is an audit result, not an
internal product report. Never transmit project findings.

Finish the substantive audit first. Then, for an eligible internal event, use
an available Python 3 launcher to prepare a bounded local report:

```text
<python-3> <skill-root>/scripts/problem_report.py --format json prepare \
  --event-code <fixed-event-code> --summary <generic-summary> \
  --outcome-code <fixed-outcome> [--exit-code <integer>]
```

Use only an event from the script's fixed enum, a generic summary, up to five
generic reproduction steps, and the bounded outcome/exit fields. Never include
project text, project paths, raw logs, prompts, attachments, environment
variables, tokens, credentials, user identity, or arbitrary metadata. Inspect
the returned preview. Reporting failure must not replace or shorten the audit.

The initial policy is unconfigured and nothing is sent. Route explicit user
intent to these deterministic actions:

- "ask before reporting internal problems" -> `configure --mode ask --transport github`
- "enable minimal automatic problem reports" -> configure `auto-minimal` only with an owner API endpoint
- "disable problem reporting" -> `configure --mode off`
- "show problem-reporting status" -> `status`
- "show the owner status for report <id>" -> `remote-status --report-id <id>` for API transport
- "delete report <id>" -> `remote-delete --report-id <id>` for API transport

For "report this internal tool problem", prepare the report and show the local
preview. In `ask` or `unconfigured` mode, send only after the user approves
that exact preview, using:

```text
<python-3> <skill-root>/scripts/problem_report.py --format json submit \
  --report <local-report-path> --approved
```

GitHub delivery verifies repository visibility. If it returns
`PUBLIC_ISSUE_APPROVAL_REQUIRED`, explain that the bounded report will be
public and obtain a second, report-specific confirmation before rerunning with
both `--approved` and `--allow-public-issue`. Never add that flag in
`auto-minimal` mode. In `off` mode, leave the report local unless the user gives
one-time approval for that exact preview.

Use the owner API for private `auto-minimal` delivery. It requires the scoped
client token in `ANALYZE_PROJECT_CLAIMS_REPORT_TOKEN`; never write that token
into policy or project files. Suspected security vulnerabilities must use the
repository's private vulnerability reporting channel, not this reporter.

## Keep installation analytics explicit and separate

Installation analytics are optional owner infrastructure, not a default skill
side effect. No public endpoint is bundled. Do not prompt, create an identity,
or send an event merely because the skill was installed, invoked, updated, or
used to report a problem. Update consent and reporting consent do not authorize
analytics.

When the user explicitly asks and an owner endpoint is available, route these
requests to `scripts/installation_analytics.py` with global options before the
verb:

- "show installation analytics status" -> `--format json status`
- "preview installation analytics" -> `--format json preview`
- "enable installation analytics for <endpoint>" -> `--format json enable --endpoint <endpoint>`
- "send an installation analytics check-in" -> `--format json check-in`
- "disable installation analytics" -> `--format json disable`
- "erase my installation analytics" -> `--format json erase`

Enabling creates local random identity but sends nothing; a later check-in is
the first network event. The scoped client token must come only from
`ANALYZE_PROJECT_CLAIMS_ANALYTICS_TOKEN`. Describe the owner metric as unique
consenting activated installations, never downloads, users, or total installs.
Do not claim a live count until the owner API is deployed and the aggregate was
actually queried.

## Run consent-gated update maintenance

At the end of each substantive invocation, after the claims result is complete
and immediately before the final response, resolve this `SKILL.md` directory
and run it with an available Python 3 launcher (`py -3` on Windows, otherwise
`python3` or `python`):

```text
<python-3> <skill-root>/scripts/update_policy.py --format json maintain
```

This applies only to a standalone installation tracked by GitHub CLI. Never
let a maintenance failure replace, shorten, or erase the substantive claims
result. Append the returned `message` and `action` only when `emit` is `true`.
An installed update becomes active on the next invocation, not the current
one. Plugin-hosted, manually copied, project-scope, pinned, duplicated, or
locally edited copies are not automatically replaced.

Route explicit user requests to these deterministic verbs:

- "enable automatic updates" -> `enable --mode auto`
- "notify me about updates" -> `enable --mode notify`
- "disable updates" -> `disable`
- "show update status" -> `status`
- "check for updates now" -> `check-now`

Keep global options such as `--format json` before the verb. Do not invent a
custom download, overwrite, unpin, or force-update path.

## Guardrails

- Lead with evidence, not advocacy.
- Preserve same-scope counterevidence.
- Do not treat artifact existence as artifact use.
- Do not treat audit invocation as independent implementation.
- Do not treat workflow completion as scientific success.
- Do not treat one dataset or task as proof of general RAG performance.
- Do not rewrite historical evidence to make a project appear consistent.
- Keep `unknown`, `failed`, `not_eligible`, and `not_proved` distinct.
