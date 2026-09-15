# Search-Assisted Claim Maintenance Plan

Status: APPROVED BY OWNER
Repository: Ian-Tseng/analyze-project-claims
Target branch: main

Integration status (2026-09-16): this document preserves the approved plan.
T1 contracts, the T2 development nominator, and T3 reviewed adapters/native
guards are implemented on the feature branch; T4-T7 remain pending. The CLI is
not installed or released, and pilot gates have not passed. See the [v1 contracts](../contracts/evidence-nomination/v1/README.md)
and [development CLI](EVIDENCE_NOMINATION_DEVELOPMENT.md).

## Intent

Extend `analyze-project-claims` with an explicit-gap local evidence nominator. Given one typed unresolved claim or component-element evidence requirement, it searches allowed repository roots and proposes exact evidence candidates without becoming a new claim-status, acceptance, installation, execution, merge, release, or publication authority.

## Proposed user outcome

A maintainer supplies one exact gap already identified by the existing audit, recorder, or reconciler. The nominator searches approved local roots and returns a reproducible bundle showing which repository excerpts may support, contradict, or contextualize that gap. The accepted map and formal record change only through the existing reconcile, human-operated acceptance, append, and verification gates.

## Initial architecture hypothesis

1. Add a corpus-read-only, candidate-only nomination stage that normalizes explicit literal terms from one typed gap request.
2. Version one supports repository-local search only. Pinned external sources and related-skill catalogs remain separately gated follow-on capabilities.
3. Persist an EvidenceNominationBundle containing the accepted-map identity, target gap, queries, allowed roots, precise locators, file hashes, bounded excerpts, exclusions, budgets, partial failures, and deterministic bundle identity.
4. Require reviewer selection before separate typed adapters create either a claim/evidence-record candidate or a component-map observation candidate. Never edit the accepted map or append a formal record during search.
5. Reuse `reconcile_component_map.py` for deterministic map comparison and exact candidate generation. Preserve the current human-operated acceptance command.
6. Keep web and related-skill search outside version one.
7. Add offline fixtures, adversarial repository-content tests, provenance tests, stale-result tests, duplicate-result tests, path-safety tests, and end-to-end candidate-only tests.

## Candidate workflow

```text
project + accepted map + one typed explicit gap
  -> validated gap request
  -> deterministic local corpus manifest
  -> literal query plan
  -> identity-bound, no-clobber evidence nomination bundle
  -> human selection
  -> typed candidate fork

ClaimEvidenceCandidateV1 branch
  -> record validate -> human review -> append-only formal record

ComponentObservationCandidateV1 branch
  -> reconcile -> exact human acceptance or rejection -> unchanged check and preflight
```

Neither branch invokes its downstream authority automatically. A component-map
acceptance does not append a claim record, and a claim-record append does not
accept or alter the component map.

## Non-goals

- Search does not establish truth, scientific validity, or general reliability.
- Search does not accept a component map or rewrite append-only history.
- Version one performs no network access and does not discover related skills.
- Search does not install, execute, update, or recursively invoke skills.
- Search does not create public issues, draft pull requests, releases, or updates without the existing consent and authority gates.
- Search does not derive the existence or status of a gap; it consumes one typed gap from the existing audit authorities.

## Deferred questions

- Exact privacy, retention, and immutable-result contracts for pinned external sources.
- Capability-gap and quality criteria that would justify related-skill discovery.
- Cross-record claim lineage and a derived current-claims view.

## Success criteria

- A local-only run produces no network access and can generate a deterministic candidate from repository evidence.
- Repeating the same frozen request and repository bytes produces the same corpus, bundle bytes, ordering, and identity.
- A search result cannot directly mutate accepted maps, formal history, installed skills, or GitHub state.
- The command opens no socket, starts no process, imports no project code, and performs no GitHub or installed-skill action.
- Existing package, component-map, formal-record, managed-update, and quality-loop tests remain green.

## Autoplan CEO premise checkpoint

The two independent CEO reviews agree that the proposal combines three products:
local repository evidence recovery, external evidence acquisition, and
related-skill discovery. They have different authority, privacy,
reproducibility, and evaluation requirements. The recommended wedge is
**explicit-gap local evidence nominations**.

Premises confirmed by the owner as option A:

1. Search is discovery, not truth, claim status, map acceptance, or record
   authority. Accepted maps and append-only records remain authoritative.
2. Version one searches allowed local roots and emits a deterministic
   EvidenceNominationBundle: queries, scope, locators, hashes, bounded excerpts,
   exclusions, budgets, and partial failures.
3. A reviewer selects nominations before separate typed adapters create either
   a claim/evidence-record candidate or a component observation candidate.
4. A claim update means proposing a new append-only record. Active-claim
   language waits for an explicit cross-record lineage/current-view contract.
5. External evidence is a later pinned-source adapter with exact outbound
   preview and approval. Mutable results remain context-only unless frozen by
   bytes and digest or an immutable object identity.
6. Related skills are later capability-gap nominations. They never become
   project evidence and search never installs, invokes, merges, or updates them.
7. Map acceptance is an explicit human-operated gate. Owner identity is claimed
   only when a separately authenticated hosted gate proves it.

Recommended sequence:

1. Explicit-gap local evidence nominator.
2. User-supplied pinned-source verifier.
3. Related-skill comparison after measured demand.
4. General web providers after privacy, provenance, quality, and retention
   gates pass.

## CEO review outcome

### Product decision

The first release is an **explicit-gap local evidence nominator**, not a search broker. Its
job is to turn one explicit unresolved claim or component-element requirement
into a small, reproducible set of repository evidence nominations that a human
can review. This preserves the product's durable advantage: discovery becomes
an auditable candidate without becoming acceptance.

The input cell is:

- exact project root and allowed sub-roots;
- accepted component-map ID and digest;
- one claim reference or component/element gap;
- closed evidence requirements and nomination budget.

The output is one immutable EvidenceNominationBundle. It may classify a result
only as a nomination for support, counterevidence, or context; it cannot assign
the formal claim status or component check status.

### Validation before expansion

Run a development pilot over 20 frozen gaps from natural repositories.
Measure top-k useful-nomination precision, missed counterevidence, false-support
rate, reviewer time, deterministic replay, and unintended mutation/network
activity. Do not add pinned external sources until the local finder materially
reduces review time without increasing false support.

### Deferred scope

General web search, persistent provider allowlists, registry crawling,
popularity-based skill ranking, automatic freshness scheduling, autonomous
claim rewriting, and all install/update/invocation behavior are explicitly
deferred.

## Decision audit log

| ID | Decision | Source | Why |
| --- | --- | --- | --- |
| D1 | Choose option A: explicit-gap repository-local evidence nominator first | Explicit owner reply `a` | Keeps discovery candidate-only, deterministic, private by default, and independently measurable before adding providers |
| A1 | Keep claim-record and component-observation candidates as separate typed payloads under a shared provenance envelope | Autoplan CEO consensus | The artifacts have different semantics and acceptance authorities |
| A2 | Describe map acceptance as human-operated, not owner-authenticated | Repository contract review | The local accept command validates candidate structure but does not authenticate a GitHub owner |
| A3 | Treat related-skill search as a later capability-gap nomination surface | Autoplan CEO consensus | Skill metadata and popularity do not prove project evidence quality |
| E1 | Consume one typed gap instead of autonomously deciding that a gap exists | Engineering consensus | Prevents a second claim-status engine |
| E2 | Bind map ID, canonical digest, and full file digest at every adapter boundary | Engineering consensus | Fails closed across semantic and lifecycle drift |
| E3 | Make literal terms explicit and normalize only; do not generate executable queries with a model | Engineering consensus | Keeps replay deterministic and repository text inert |
| E4 | Deterministic caps may yield partial results; wall timeout yields no bundle | Engineering consensus | Runtime scheduling cannot change semantic identity |
| X1 | Use one public preflight, nominate, show, verify, and compile CLI | DX consensus | Keeps the journey explicit while printing the next safe handoff |
| X2 | Require an output directory and keep sidecars outside validation | DX consensus | Local excerpts are review artifacts, not authority, and should not be retained silently |
| X3 | Freeze a 20-gap pilot and measurable advance gates | CEO, engineering, and DX consensus | Provider expansion requires observed local value and zero authority violations |

## Engineering review outcome

### Architecture and integration

Implement a separate `evidence_nomination.py` command and internal module. Do
not add search behavior to the component reconciler or v2 recorder.

1. Validate one closed `LocalEvidenceGapRequestV1`.
2. Preflight the accepted map and, for claim targets, the exact persisted v2
   record.
3. Enumerate allowed roots into a sorted, bounded corpus manifest.
4. Run deterministic literal matching and integer scoring.
5. Write one immutable `EvidenceNominationBundleV1`.
6. Validate one explicit `EvidenceNominationSelectionV1`.
7. Compile either a `ClaimEvidenceCandidateV1` or
   `ComponentObservationCandidateV1`.
8. Stop before existing validate, append, reconcile, or accept operations.

The component adapter may only add selected local locators to an existing
element. New elements, target changes, check status, claim status, strongest
claim, rationale, limitations, and evidence roles remain explicit reviewer
inputs enforced by existing schemas.

Add expected-map ID, canonical-payload digest, and full-file digest guards to
reconcile and v2 validate/append. Search-generated candidates must pass all
three so map drift cannot reuse an old element reference.

### Closed data contracts and identity

- Gap request: exact map identities; target union for one component/element or
  one `{record_sha256, scan_id, claim_id, claim_digest, element_ref}`; allowed
  roots; explicit `all_terms`, `any_terms`, and `exclude_terms`; resource
  policy.
- Bundle: normalized request, finder/code/schema identities, sorted corpus
  snapshot, query IDs, bounded nominations, exclusions, deterministic budget
  truncation, completeness state, and canonical payload digest.
- Selection: exact bundle ID and digest plus included nomination IDs, reviewer
  evidence role, bounded observed summary, and rationale. A reviewer label is
  informational and unauthenticated.
- Candidate: shared exact provenance envelope plus one closed typed payload.
  Keep the selection and bundle as sidecars because scan-record v2 has no typed
  nomination-lineage field.

Use POSIX repository-relative paths and raw-byte source/selection digests.
`bundle_id` hashes stable request, corpus, queries, nominations, exclusions,
and deterministic truncation. Exclude timestamps, runtime duration, absolute
paths, output locations, platform error strings, and random IDs from semantic
identity.

### Trust boundary

Use standard-library code only. The finder must not call subprocesses, Git,
network APIs, model APIs, plugins, update paths, or project code. Reject path
escape, absolute paths, overlapping roots, symlinks, junctions/reparse points,
Windows alternate data streams and device names, archives, binary/non-UTF-8
files, Git LFS pointers, unsafe Unicode controls, oversized files, unstable
before/after reads, and secret-bearing excerpts. Never echo rejected sensitive
content. Map-declared paths outside the approved roots are data, not permission.

### Deterministic budgets

Version-one defaults are 2,500 files, 64 MiB total input, 1 MiB per file, eight
requirements, 5,000 raw matches, five nominations per requirement, 20 total
nominations, 2 KiB per displayed excerpt, and 64 KiB per selected range.
Enumerate by normalized path and rank by `score desc, path, byte start, byte
end, query_id`. Count/byte caps may produce a deterministic partial bundle;
the 10-second safety timeout aborts without a bundle so wall-clock timing cannot
change semantic output.

### Test matrix

- closed-schema, canonical identity, golden replay, CRLF, Unicode, path-case,
  and code/schema-drift tests;
- all/any/exclude matching, requested nomination roles, scoring, tie-breaking,
  duplicate merging, zero results, and every budget edge;
- map/record/source/bundle/selection/candidate stale or tampered identities;
- traversal, absolute paths, links/reparse points, ADS/device names, unstable
  reads, permissions, binary/UTF-16, LFS, archives, secrets, and control text;
- socket, subprocess, import, accepted-map, history, installation, and GitHub
  mutation canaries;
- component adapter emits observation-shaped evidence and never accepts;
- claim adapter never infers status/bindings and stops at v2 validation;
- all existing mapper, recorder, package, plugin, update, and quality-loop
  regressions remain green.

### Implementation stages

1. Freeze schemas, identity rules, budgets, path policy, and golden fixtures.
2. Implement accepted-map/record preflight and request validation.
3. Implement the deterministic corpus scanner and bundle writer.
4. Implement selection validation and the claim candidate adapter.
5. Implement the locator-only component observation adapter and map guards.
6. Update package descriptors, manifest, documentation, map, and formal record.
7. Run the frozen 20-gap pilot before any external or skill-search adapter.

## Developer-experience review outcome

### Personas and operator journey

- Maintainer: investigate one gap already emitted by an audit or reconciler.
- Claim reviewer: select candidate excerpts and assign an evidence role.
- CI/evaluator: replay frozen requests and verify exact identities without
  selecting or accepting anything.
- Codex/Claude operator: prepare or explain inputs while the Python CLI remains
  the deterministic execution authority.

Expose one public `scripts/evidence_nomination.py` command:

```text
preflight --request <request> --project-root <root> --map-root <map> [--record <record>]
nominate  --request <request> --project-root <root> --map-root <map> [--record <record>] --out-dir <dir>
show      --bundle <bundle> [--format human|json]
verify    --bundle <bundle> --project-root <root> --map-root <map> [--record <record>] [--format human|json]
compile   --bundle <bundle> --selection <selection> --project-root <root> --map-root <map> [--record <record>] --output <candidate>
```

`nominate` performs preflight and writes a bundle plus an empty selection
template. `preflight` exists for diagnosis. `compile` infers claim versus
component from the closed target union and prints, but never executes, the
exact existing validate or reconcile handoff.

First run is nominate, show, edit the generated selection, compile, then run the
printed existing validator/reconciler command. Repeat use is nominate plus
verify; identical inputs return `reused_identical`.

### Output, errors, and artifact lifecycle

Default output is a short human summary; `--format json` emits one object.
Every receipt includes `schema_version`, `status`, stable `code`, `effect`,
`changed`, `retryable`, artifact path and digest, target reference,
nomination counts, completeness, exclusion/truncation reasons,
`network: false`, `accepted_state_changed: false`, `next_command`, and
documentation link. Errors add Problem, Cause, Effect, Fix, and exact Retry
guidance without echoing sensitive content.

Exit 0 covers complete, deterministic partial, zero-nomination, and identical
reuse outcomes. Exit 2 is invalid input or safety refusal; 3 is retryable local
I/O or timeout with no artifact; 4 is stale/tampered identity; 5 is an atomic
write/recovery failure. Diagnostics use stderr.

Require `--out-dir` on first use. Recommend:

```text
.analyze-project-claims/nominations/
  <bundle-id>.bundle.json
  <bundle-id>.selection.json
  <bundle-id>.<claim|component>.candidate.json
```

These files may contain local excerpts, stay outside `validation/`, and should
be ignored unless explicitly reviewed for commit. Immutable operationally
means atomic exclusive creation, content-derived identity, identical reuse, and
refusal to overwrite different bytes; it is not a filesystem immutability
claim.

### Quickstart and cross-agent boundary

Add `examples/evidence-nomination/minimal/` with a tiny UTF-8 repository,
accepted map, component request, known support/counter/context hits, golden
bundle, ready selection, and expected candidate. Windows `py -3` and POSIX
`python3` commands must produce the named bundle in under five minutes,
preferably under one minute, without editing JSON before the first result.

Codex and Claude may prepare a request or explain output. They must not silently
infer the gap, terms, evidence role, claim status, or acceptance. No hook
auto-runs nomination. Client discovery/invocation remains separately evidenced.

### Documentation and pilot gates

Update README with the local-only outcome, two-command quickstart, and the
nomination-is-not-acceptance boundary. Add a packaged nomination reference for
schemas, roles, budgets, errors, lifecycle, and recovery.
Link the claim handoff from the evidence-bound record guide, the locator-only
handoff from the component protocol, and mark sidecars non-authoritative in
validation/README.

Freeze 20 gaps before the pilot: ten claim targets and ten component targets
across at least four natural repositories, including independently labeled
counterevidence and insufficient or zero-result cases. Advance only if:

- useful nomination precision at five is at least 0.70;
- false-support nomination rate is at most 0.05;
- missed-counterevidence rate is at most 0.10;
- paired median reviewer time falls by at least 30 percent;
- selection-to-valid-candidate conversion is at least 0.80;
- golden replay is byte-identical on Windows, macOS, and Linux; and
- network, process, import, accepted-state, and installation mutations are zero.

These are development gates for the frozen sample, not a reliability claim
across projects or domains.

## Planned file map

Create:

- `skills/analyze-project-claims/scripts/evidence_nomination.py`;
- `skills/analyze-project-claims/scripts/_internal/evidence_nomination/`;
- five closed request, bundle, selection, claim-candidate, and
  component-candidate schemas under `references/`;
- matching safe templates under `assets/`;
- a finder identity descriptor and packaged reference guide;
- `examples/evidence-nomination/minimal/`;
- focused contract, security, adapter, and end-to-end test modules.

Modify:

- `reconcile_component_map.py` and recorder v2 entry points for expected-map
  identity guards;
- package manifest, descriptor tests, README, component protocol,
  evidence-bound guide, validation authority, publishing checklist, changelog,
  version, citation, plugin metadata, and packaged skill instructions;
- component-map observation, accepted map after explicit acceptance, validation
  receipt, and a new append-only formal record/report.

## Failure and rescue registry

| Condition | Result | Recovery |
| --- | --- | --- |
| Invalid request or unknown target | Exit 2; no artifact | Start from the template and bind an existing exact target |
| Map or record identity drift | Exit 4; no candidate | Re-preflight and create a request against current authority |
| Unsafe root, link, path, or secret excerpt | Refuse or record a content-free exclusion | Narrow roots or remove unsafe input; never echo content |
| No matches | Complete zero-nomination bundle | Refine explicit terms or record the unresolved gap |
| Count or byte cap reached | Deterministic PARTIAL bundle | Review partial scope or explicitly raise a bounded cap |
| Wall timeout | Exit 3; no bundle | Reduce roots or caps and retry |
| Existing identical output | Reuse exact artifact | Continue with show or verify |
| Existing different output | No-clobber refusal | Choose a clean output directory |
| Source changes before compile | Exit 4; candidate not written | Rerun nomination and selection |
| Invalid human selection | Exit 2; candidate not written | Correct roles, summaries, or required reviewer fields |
| Existing validator rejects candidate | Preserve sidecars; no authority change | Repair reviewer-authored semantics and compile again |
| Atomic write cannot complete | Exit 5 with recovery path | Inspect temporary/output paths; never assume rollback |

## Implementation tasks

- [x] **T1 (P1, human: 2 days / Codex: 3 hours) - Freeze contracts.**
  Add five schemas, templates, canonical identities, budgets, exit codes, path
  rules, and golden fixtures before runtime code. Implemented in
  `contracts/evidence-nomination/v1/` with synthetic vectors and contract tests;
  installation/package authority remains T6.
- [x] **T2 (P1, human: 4 days / Codex: 6 hours) - Build the nominator.**
  Implement preflight, safe corpus enumeration, literal matching, deterministic
  ranking, bundle creation, show, verify, atomic no-clobber writes, and receipts.
  Implemented as repository-level development scripts; the broader
  cross-platform/adversarial audit remains T4.
- [x] **T3 (P1, human: 4 days / Codex: 8 hours) - Build adapters and drift guards.**
  Add selection validation, claim/component compilers, triple map-identity
  guards, and candidate-only existing-command handoffs. Implemented with an
  explicit provenance-checking `handoff` before native payload use. Native
  development identities were rebuilt for these source changes; T6 release
  reconciliation, acceptance, and formal evidence remain pending.
- [ ] **T4 (P1, human: 3 days / Codex: 6 hours) - Close adversarial paths.**
  Cover link/reparse, ADS/device, traversal, race, secrets, Unicode, binary,
  LFS, caps, timeout, mutation canaries, and cross-platform replay.
- [ ] **T5 (P2, human: 2 days / Codex: 4 hours) - Finish the public journey.**
  Add the minimal fixture, Windows/POSIX quickstarts, reference guide, error
  recovery, artifact lifecycle, and Codex/Claude boundaries.
- [ ] **T6 (P1, human: 2 days / Codex: 4 hours) - Rebuild release authority.**
  Update package identities, reconcile the exact map, obtain explicit
  acceptance, reconcile unchanged, run the complete suite, and append a fresh
  formal record/report without rewriting history.
- [ ] **T7 (P2, human: 3-5 days / Codex: 1 day) - Run the frozen pilot.**
  Freeze 20 labeled gaps, collect paired manual/nominator measurements, compute
  every advance gate, and retain external/skill search as deferred unless all
  thresholds pass.

## GSTACK REVIEW REPORT

Status: APPROVED BY OWNER

### Plan summary

Build an explicit-gap, repository-local evidence nominator as a separate,
standard-library subsystem. It converts one authority-identified gap into
identity-bound candidate excerpts and stops before all existing semantic and
structural acceptance gates. General web search and related-skill discovery
remain later phases gated by measured local value.

### Decisions

Eleven decisions are recorded: one explicit owner choice and ten auto-decisions
from the CEO, engineering, and DX consensus. No unresolved taste choice remains.
The original broader search-broker direction was challenged by both CEO voices
and resolved when the owner selected option A.

### Review scores

- CEO: 9/10 after narrowing the wedge; both voices confirmed six of six themes.
- Design: skipped because this release has no UI scope.
- Engineering: 9/10; both voices confirmed six of six architecture themes.
- DX: 9/10; both voices confirmed six of six operator-journey themes.

### Cross-phase themes

- Discovery is never acceptance. Every phase independently required
  candidate-only output and reuse of existing authorities.
- Deterministic provenance is the product advantage. Every phase required exact
  identities, frozen inputs, no hidden provider behavior, and replay.
- Related-skill search is a separate product lane. CEO and engineering kept it
  out of project evidence; DX kept it out of automatic activation.
- The operator must see the boundary. Engineering and DX required typed
  sidecars, stable errors, no-clobber behavior, and the exact next safe command.

### Deferred

- Pinned external-source verification waits for the local pilot.
- Web providers, retention policy, and outbound privacy approval wait for the
  pinned-source contract.
- Related-skill comparison waits for a measured capability gap.
- Active-claim updates wait for cross-record lineage/current-view authority.
- No item was placed in TODOS.md because this repository has no active TODOS.md;
  all deferred items remain explicit in this plan.

### Final gate

Approval authorizes implementation planning against this file. It does not
authorize component-map acceptance, merge, publication, installation,
activation, network search, or related-skill installation.

Owner approval: explicit final-gate reply `a` on 2026-08-30.
