<!-- /autoplan restore point: C:\Users\chois\.gstack\projects\analyze-project-claims\feature-cross-skill-managed-lifecycle-v081-autoplan-restore-20260820-224822.md -->
# Managed Skill Fleet Lifecycle v0.8.1 Plan

Status: APPROVED — implementation authorized 2026-08-20

## Product objective

Maintain a trustworthy fleet of independently released `Ian-Tseng` skills through one auditable lifecycle protocol while keeping execution, update, reporting, repair, and release permissions separate.

For supported managed invocations, each producer skill runs a bounded local maintenance entry point after its substantive result. The fast path normally checks only a local lease and policy. Network discovery is rate-limited. Replacement is consent-bound, performed by the native installer or plugin manager, and verified before a fresh host invocation activates it. Material quality signals produce content-free receipts that `analyze-project-claims` can consume and, with explicit confirmation, route to the exact producer repository. A separate owner-controlled workflow may create an independently validated draft repair PR.

This plan does not promise that every host or every stop event invokes an LLM skill. It defines measurable behavior for supported managed invocations and reports unsupported coverage honestly.

## CEO review verdict

Mode: SELECTIVE EXPANSION.

The initial direction was correct but over-coupled three different products: local lifecycle maintenance, bounded quality intake, and repository repair. The recommended architecture is a Managed Skill Fleet Kit: a full-commit-SHA-pinned reusable GitHub Actions workflow, a closed repository-local policy, and a thin caller in each producer repository. Onboard all three producers in code, then activate them through a two-repository canary before fleet-wide enablement.

The two independent CEO voices agreed on the control-plane choice, the need to replace “self-update” language with consent-bound installer-managed replacement, the need for stronger write authorization than a label alone, and the need to rebuild evidence only after the architecture stabilizes. Claude CLI was unavailable; the outside voice was an independent fresh-context agent and the second voice was Codex CLI.

## Premise challenge

The product is not “a skill that updates itself every time it runs.” That framing is both technically unprovable and trust-eroding. The product is a managed lifecycle protocol with four outcomes:

1. Installation and source identity are unambiguous.
2. Update eligibility is checked within an explicit freshness target.
3. Bounded quality signals reach the correct owner without project content.
4. Approved repairs become independently validated draft candidates without gaining merge, release, publication, or activation authority.

Invocation-driven maintenance is one transport for this protocol, not its authority boundary or scheduler.

## Existing leverage

- `analyze-project-claims` already has fail-closed update-authority checks, a bounded receipt queue, explicit public-submission confirmation, dynamic `Ian-Tseng/<producer_repository>` routing, and an analyzer-specific protected maintainer implementation.
- `audit-method-data-flow`, `audit-venue-submission`, and `server-ops` already have in-progress managed-updater and outcome-receipt integrations.
- The analyzer already separates unprivileged agent execution, secret-free validation, guarded patch publication, human evidence acceptance, and release authority.
- Package manifests, component maps, formal validation records, release guides, and install/update smoke-test contracts already exist in the stronger repositories.
- The existing implementation is a useful reference, but its copy-six-files adoption model would drift across repositories.

## Dream state

A new `Ian-Tseng` skill joins the fleet by adding one validated policy file and one small SHA-pinned workflow caller. A doctor reports protocol compatibility, workflow pin, repository protections, package identity, and last canary status. Local invocations usually pay only a lease-file fast path. Quality receipts remain local until a user explicitly previews and confirms a bounded public issue. Repair requires a protected environment approval bound to immutable inputs. The agent never holds repository write credentials. A fresh validation job proves the exact patch, and a final job with narrowly scoped caller-repository authority opens only a draft PR. Human review retains map acceptance, merge, release, publication, and activation.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Duplicate the analyzer workflow and Python service into every repository | Reject | Fast initially, but security fixes, action pins, schemas, and repair semantics drift. |
| Central reusable workflow, full-SHA pin, thin local caller/policy | Choose | Centralizes dangerous mechanics while preserving caller policy, permissions, protection, and rollback. |
| GitHub Agentic Workflows as the foundational control plane | Defer | Useful future backend, but public preview and not a replacement for local update or release authority. |
| Central GitHub App | Defer | Adds privileged credentials, installation lifecycle, uptime, incident response, and tenant isolation obligations. |

GitHub’s reusable-workflow contract supports public cross-repository calls; the caller’s token permissions can only be maintained or reduced, and full commit SHA is the safest reference.

## Scope decisions

### Accepted scope

- Create a versioned, closed managed-skill policy schema and conformance validator.
- Create a central reusable repair workflow in the analyzer repository, pinned by callers to a full commit SHA.
- Add thin callers and exact repository policies for `audit-method-data-flow`, `audit-venue-submission`, and `server-ops`.
- Define shared receipt semantics, compatibility ranges, bounded lifecycle budgets, deduplication, rollback, and stale-pin detection.
- Keep update replacement delegated to the native GitHub skill or plugin manager.
- Require protected-environment approval before agent execution and separately before draft publication if the latter receives write authority.
- Bind approvals to repository, issue number and body digest, base SHA, workflow SHA, policy digest, and attempt nonce; edits or relabels invalidate the binding.
- Onboard all three producers, then prove two repositories as canaries before enabling the third production repair loop.
- Rebuild all changed manifests, component maps, test receipts, and formal evidence after implementation. The user has pre-authorized acceptance only for the three rebuilt candidates that exactly match this approved plan.

### Not in scope

- A promise that every client, host, stop event, or skill invocation triggers analysis.
- Silent or unconditional package mutation.
- Multi-owner or arbitrary third-party repository routing.
- Raw project content, prompts, paths, evidence excerpts, secrets, or arbitrary issue text in receipts or public issues.
- Automatic evidence-map acceptance by the agent.
- Automatic merge, release, tag, publication, issue closure, or installed activation.
- A GitHub App, fleet daemon, or mandatory GitHub Agentic Workflows dependency.
- A workflow that rewrites or approves its own central workflow pin.
- Automatic repair for `no_issue`, informational, aggregate-only, or non-reproducible signals.

## Architecture review

The design has three planes with separate authority:

```text
supported skill invocation
  -> local lease/policy decision
  -> native installer/plugin-manager replacement (only if consent + identity pass)
  -> bounded local outcome receipt

explicit analyzer consume + user confirmation
  -> content-free issue in exact Ian-Tseng producer repository

owner triage + protected environment approval
  -> SHA-pinned central reusable repair workflow
  -> unprivileged, credential-free agent patch
  -> fresh secret-free validation
  -> separately authorized draft PR publication
  -> human review / evidence acceptance / merge / release
```

Repository-local policy is authoritative for repository identity, package roots, mutable and denied paths, named validation profiles, version-identity files, schema compatibility, required environments, and draft-only behavior. It is data, not a scripting language: no arbitrary shell strings, templates, expressions, or permission expansion.

The central workflow owns exact intake validation, immutable binding, agent sandboxing, patch transport, fresh validation, and publication mechanics. Its helpers are central composite or JavaScript actions referenced with GitHub Cloud's `$/path/to/action` syntax, which resolves to the called workflow repository at the running workflow commit. Caller source is checked out separately at the bound base SHA. GitHub Enterprise Server is not supported in v0.8.1 because it lacks `$/`. The caller owns token permissions and cannot be elevated by the called workflow. Callers pass secrets explicitly; `secrets: inherit` is prohibited.

The public reusable workflow uses `on.workflow_call` with a narrow typed interface and one canonical policy path. The thin caller owns the `issues:labeled` trigger and invokes:

```yaml
uses: Ian-Tseng/analyze-project-claims/.github/workflows/managed-skill-repair.yml@<40-hex-reviewed-sha>
```

The workflow exposes no arbitrary command, script, prompt, path, or permission inputs.

## Error and rescue map

| Failure | Default behavior | User rescue |
|---|---|---|
| Ambiguous, pinned, modified, project-local, or source-mismatched install | Refuse replacement; preserve current install | Run doctor, remove ambiguity or choose manual update |
| Active success lease | Skip network and return silently | Use explicit `check-now` |
| Remote timeout or offline host | Preserve primary result and current install | Retry later; inspect local receipt |
| Receipt expired, duplicated, malformed, or queue-full | Quarantine/reclaim invalid state; never starve newer valid receipts | Run receipt doctor or clear only named local state |
| Unsupported host continuation | Report coverage as not observed | Explicitly invoke analyzer consume |
| Destination repository mismatch | Refuse issue creation | Correct producer identity and regenerate receipt |
| Issue edited or relabeled after approval | Invalidate approval | Re-triage and approve a new nonce |
| Policy/workflow schema mismatch | Fail before agent execution | Update caller pin or policy through a human-reviewed PR |
| Agent proposes denied-path change | Reject patch | Narrow task or perform manual repair |
| Validation fails | Publish no branch or PR | Inspect secret-free validation artifact and retry from a new base SHA |
| Draft creation outcome is uncertain | Do not retry automatically | Reconcile known head, issue, and PR state first |
| Bad central workflow SHA | Stop adopting or revoke in policy | Human rollback PR to last reviewed SHA |

## Security and threat model

- The public issue is untrusted triage input. Its body is schema-bounded and never passed raw to the agent.
- An exact owner-applied label establishes eligibility, not write authorization.
- Protected-environment approval is explicit repair authorization, bound to immutable inputs and consumed once.
- The candidate job has no repository-write token. After the model exits, only a preinstalled root-owned, immutable, non-interpreting collector and pinned artifact uploader may run; neither executes candidate code. The collector terminates survivor processes, protects base Git identity, enforces the patch boundary, and emits an exact digest.
- Validation runs fresh from the base plus exact patch artifact, with no agent secret and no write token.
- Publication runs only after validation and receives minimum caller-repository permissions.
- Cross-repository PATs are not the default. Prefer the caller repository’s `GITHUB_TOKEN`; if unavailable, use a per-repository fine-grained token, never a fleet-wide token.
- Workflow, policy, action, schema, base, and issue identities are digest-bound. Replays and relabels deduplicate.
- Denied control planes include `.github/workflows`, branch protection configuration, release automation, validation authority, accepted maps, credential files, and the workflow pin itself.

## Data flow and edge cases

1. The producer completes its substantive result.
2. Its maintenance tail checks eligibility and a 24-hour success lease; the local target is under 50 ms.
3. If due, bounded discovery checks update availability with a hard timeout. Mutation requires pre-bound local consent plus revalidated installation and source identity.
4. The producer emits at most one bounded receipt at a durable completion boundary. `requested_action: none` is a no-op.
5. Analyzer consumption deduplicates, expires stale entries, and creates a local proposal only for actionable triage classes.
6. The user previews exact destination, fields, and public visibility, then explicitly confirms submission.
7. The producer workflow independently validates owner, open issue, exact label, receipt schema, repository binding, and replay state.
8. The first protected environment, `managed-repair-agent`, gates candidate execution. Its run summary presents a canonical authorization manifest containing repository ID and name, issue node ID and number, issue body and label-state digests, issue `updated_at`, base SHA, policy digest, workflow SHA, nonce, and expiry.
9. After approval, the workflow refetches live issue, label, default-branch head, policy, and workflow state. Any mismatch invalidates the attempt.
10. The unprivileged job generates a patch within allowed paths.
11. A separate job validates the exact patch from a clean base with no write permission, no candidate-controlled cache, bounded pre-fetched dependencies, and network denial while candidate code runs.
12. The second protected environment, `managed-repair-publish`, gates write authority. It repeats live-state validation and reconciles deterministic remote state before mutation.
13. The publication job creates or confirms one draft PR and records a truthful idempotent outcome.

The authorization ID is the SHA-256 of the canonical manifest. Its deterministic branch is derived from that ID. Before each write, publication queries the branch, tree, PR, and issue-comment state: an exact prior state is confirmed success; a missing later object resumes from the next safe operation; a conflicting tree is a collision; a timeout is uncertain and reconciled before any retry. It never force-pushes. Concurrency is keyed by repository and issue but is scheduling, not the correctness boundary. Clock rollback cannot extend a lease indefinitely. A stale queue entry cannot block a fresh receipt.

## Code quality review

- Factor shared protocol and schema logic into one versioned fleet-kit surface; keep repository adapters declarative and small.
- Reuse proven intake, patch-guard, validation, and contribution concepts without copying repository-specific code.
- Keep update-policy code locally packaged because it must operate offline and validate the installed tree; share its contract through conformance tests and generation, not remote runtime imports.
- Require explicit ordinary-file enumeration in manifests and evidence maps. Reject symlink/reparse roots, children, outputs, traversal keys, unknown metadata, and unbounded reads.
- Use typed error codes and operation-aware safety messages.
- Keep the central policy schema closed and versioned with documented compatibility.

The minimum policy fields are: schema and protocol version; exact numeric repository ID plus owner/name; exact package roots; normalized allowed roots; additive denied paths; version-identity files; one central validation-profile ID with bounded parameters; authorized triagers and trigger label; the two fixed environment names; `draft_only: true`; compatibility range; and an explicit local enable flag. Parsing rejects duplicate and unknown keys, oversized values, traversal, Unicode/case collisions, symlink/reparse/submodule roots, shell strings, dynamic `uses`, and policy attempts to weaken central hard denials.

## Test review

- Policy schema matrix, unknown-key rejection, repository/owner/path binding, and schema compatibility.
- Workflow contract tests for immutable pins, permission monotonicity, no `secrets: inherit`, protected environments, denied paths, and draft-only publication.
- Issue-edit, relabel, replay, concurrent attempt, stale base, stale pin, and consumed nonce cases.
- Agent credential absence and unprivileged execution assertions.
- Exact patch reproduction in a clean validation job and fail-closed validation profiles.
- Local fast-path lease, offline timeout, concurrent hosts, clock rollback, pinned/modified/ambiguous installs, rollback, and fresh activation.
- Receipt expiry, capacity reclamation, no-op semantics, future timestamps, tamper, and content-free transport.
- Windows/Linux/macOS package and filesystem boundary cases.
- Publisher checkout, standalone, plugin, duplicate-install, Claude, and Codex matrices.
- Evidence-map exact-byte identity from staged/exported trees.
- Central helper provenance through `$/`, caller checkout semantics, hidden-artifact regression, and exact artifact ID/digest propagation.
- Deterministic publication fault injection before push, after push, after PR creation, and after issue comment, including uncertain-outcome reconciliation.
- Environment provisioning, disabled or missing protection, admin bypass, self-review policy, caller Actions allowlist, and the repository setting that permits Actions-created PRs.
- Atomic cutover tests proving the legacy workflow and new caller cannot double-trigger.

Live acceptance requires one real N→N+1 standalone replacement plus fresh activation, one plugin-manager path, and one report → approval → validated draft PR canary. Local simulations cannot be described as those observations.

## Performance review

- Active-lease path target: under 50 ms, zero network, zero process spawn where feasible.
- Remote discovery has a hard timeout and does not alter the substantive skill result.
- At most one check is active per installation; concurrent invocations share lease/lock state.
- Repair concurrency is one run per repository and issue.
- Validation profiles have time and artifact-size budgets.

## Observability and debuggability review

The fleet doctor reports installation/manager authority, package/source identity, consent, lease, policy compatibility, central workflow SHA, protection readiness, last canary, receipt health, and lagging pins without secrets or project content.

Every repair attempt records repository, issue, base SHA, policy digest, workflow SHA, attempt nonce, validation result, and draft PR URL or truthful uncertainty state. Logs use typed reason codes and redact paths, argv values, credentials, queries, and user content.

## Deployment and rollout review

1. Stabilize the schema, conformance suite, and reusable workflow in the analyzer repository.
2. Add thin callers and policies to all three producers, with live repair unavailable until local conformance passes.
3. Canary `audit-method-data-flow` first.
4. Canary `audit-venue-submission` second.
5. Demonstrate workflow-SHA rollback, replay rejection, the public issue boundary, and a real validated draft PR.
6. Enable `server-ops` after both canaries pass.
7. Rebuild package manifests, maps, receipts, and formal records from exact staged bytes; accept only exact current candidates, then reconcile unchanged.
8. Open PRs, require PR/main CI, verify GitHub settings, publish each version once, and run cross-machine install/update/fresh-activation smoke tests.

Emergency response is caller-owned: disable the caller, remove the trigger label, lock the protected environments, revoke the per-repository secret if any, and submit a human-reviewed rollback PR for the last compatible workflow-SHA and policy pair. A central bad-SHA list is advisory for the fleet doctor because a bad pinned workflow cannot safely revoke itself. Keep the last two workflow SHAs and schema versions runnable during rollout. The workflow never updates its own pin.

Cutover is atomic. A canary-only label or `workflow_dispatch` dry run proves configuration first; the legacy trigger is then disabled in the same reviewed change that enables the pinned caller. Missing or unprotected environment names are a provisioning failure, not something the workflow may create or accept.

## Long-term trajectory review

The fleet kit is one step below a GitHub App. If fleet scale or owner diversity grows enough to justify a service, the same schema and receipts can become its contract. GitHub Agentic Workflows may later replace part of execution after public-preview and permission risks are reevaluated. Neither future changes local installer authority, bounded reporting, human evidence acceptance, or release separation.

## Design and UX review

Skipped: no graphical interface is in scope. Operator and developer experience is reviewed in the DX phase.

## Failure modes registry

| ID | Failure mode | Prevention or detection | Blocker |
|---|---|---|---|
| F1 | Maintenance is understood as remote activity on every use | Precise supported-invocation and lease wording | Yes |
| F2 | Label replay starts repeated attempts | Two environment approvals, immutable nonce, deterministic reconciliation | Yes |
| F3 | Central compromise reaches all callers | Full-SHA pins, caller disablement, human SHA/policy rollback | Yes |
| F4 | Policy becomes arbitrary code | Closed schema and named validation profiles | Yes |
| F5 | Agent gets repository credentials | Credential-free candidate job and immutable post-agent collector | Yes |
| F6 | Validation runs a modified control plane | Denied paths and fresh base-plus-patch validation | Yes |
| F7 | Public report leaks content | Content-free schema, preview, explicit confirmation | Yes |
| F8 | Updater replaces wrong install | Source, topology, manifest, and consent verification | Yes |
| F9 | Stale evidence is accepted | Exact staged-byte rebuild and unchanged reconcile | Yes |
| F10 | Canary is overclaimed as a fleet guarantee | Explicit evidence scope and compatibility matrix | Yes |

## Completion criteria

- All three policies and thin callers validate against one protocol.
- The central workflow is pinned by immutable SHA and cannot elevate caller permissions.
- Protected approval, immutable binding, replay prevention, unprivileged execution, secret-free validation, and draft-only publication are proven.
- Two live producer canaries pass before the third repair loop is enabled.
- Local update and receipt contracts pass across supported matrices; unsupported cells are marked not observed.
- Three rebuilt exact component-map candidates match the approved implementation and are owner-accepted, followed by unchanged reconciliation and fresh formal records.
- PR/main CI, release, public install/update, and another-machine activation finish before related claims become `VERIFIED`.

## Decision audit trail

| Decision | Result | Basis |
|---|---|---|
| Control plane | Full-SHA reusable workflow plus local caller/policy | Both CEO voices and GitHub’s reuse/permission model |
| Product language | Managed lifecycle and consent-bound replacement | Native manager is mutation authority |
| “Every use” | Supported managed-invocation contract | Hosts cannot guarantee invocation |
| Repair authorization | Protected environment bound to immutable inputs | Label is triage, not sufficient consent |
| Secrets | Explicit minimum; no inheritance or fleet PAT | Least privilege |
| Rollout | Onboard three, activate method and venue canaries, then server | User scope with bounded blast radius |
| Evidence | Rebuild after implementation, accept exact current only | Preliminary candidates predate review |
| Future platform | Defer App and Agentic Workflows | Avoid premature privileged/public-preview dependency |

## Dream state delta

Existing repositories have most local safety primitives but lack a shared policy schema, central pinned workflow, immutable approval binding, fleet doctor, canary contract, and common conformance. These are v0.8.1 leverage points. Existing producer updater and receipt code is retained where it conforms.

## Implementation tasks

1. Specify the closed policy schema, compatibility, named validation profiles, and lifecycle/receipt protocol.
2. Refactor the analyzer maintainer into a public reusable workflow with isolated agent, validation, and publication jobs.
3. Add conformance and boundary tests, fleet doctor, pin reporting, and rollback guidance.
4. Add thin pinned callers and exact policies to method, venue, and server.
5. Align each skill’s maintenance tail, updater, receipt, docs, manifests, and compatibility matrix.
6. Run the two-repository canary; enable the third only after gates pass.
7. Rebuild exact package/evidence identities; accept the three rebuilt candidates only if they match this plan.
8. Commit, push, PR, main CI, publish, and perform public cross-machine evidence in release order.

## Engineering review outcome

Both engineering voices returned CONDITIONAL GO on the architecture and NO-GO on the current implementation snapshot. The plan resolves their material findings as follows:

- Add a new reusable `workflow_call` surface rather than mutating the legacy event workflow in place.
- Centralize helpers with GitHub Cloud `$/` actions at the workflow commit; keep only a policy and thin caller in producers.
- Use two protected environments: one before costly agent execution, one before write-capable publication.
- Replace the incorrect “agent is final step” statement with the exact trusted-collector boundary.
- Use a canonical authorization manifest, post-approval live-state refetch, deterministic publication identity, and remote reconciliation.
- Make emergency disablement and compatible SHA/policy rollback caller-owned.
- Stage an atomic legacy-to-caller cutover and require live GitHub canaries for environment, token, helper-resolution, and PR-check behavior.

The canary order is fixed: method, venue, then server. These are no longer open architecture decisions; the remaining gate is approval of the complete reviewed plan.

## Developer experience review

Both DX voices returned CONDITIONAL GO on the architecture and NO-GO on the current owner journey. The strongest existing feature is evidence honesty: distribution, client discovery, invocation, replacement, repair, release, and activation are kept separate. The largest gap is that the public guide still teaches the legacy copy-six-files model while this plan chooses a policy-and-caller fleet kit.

### Persona card

| Persona | Goal | Safe first success |
|---|---|---|
| Codex user | Install one managed skill without topology ambiguity | One tracked install, exact identity shown, doctor ready, first invocation complete |
| Claude Code user on another PC | Prove installation, discovery, invocation, later replacement, and activation separately | /skills discovery plus fixture invocation; replacement remains a later evidence cell |
| Producer maintainer | Join a repository without copying a security service | Deterministic policy/caller, LOCAL_READY, onboarding PR ready |
| Fleet owner | Diagnose stale pins and recover from bad or uncertain operations | One doctor/reconciliation view with a safe next command |

### Empathy narrative

The ordinary user should never infer whether Codex standalone, Codex plugin, Claude target, project copy, or publisher checkout owns a visible skill. The producer maintainer should not reverse-engineer security boundaries from six copied files. Under incident pressure, the fleet owner must see whether no remote object exists, only a branch exists, a draft PR exists, or the outcome is unknown, then receive one safe query before mutation.

### Magical moment

From a clean producer checkout:

~~~powershell
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py init --repository Ian-Tseng/REPOSITORY --skill SKILL --package-root skills/SKILL --workflow-sha <40-hex-sha>
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py validate --repo-root .
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py doctor --local --repo-root .
~~~

The first command previews exactly two deterministic files and changes nothing; --apply is separate. The next commands return LOCAL_READY, exact workflow SHA and policy digest, and remaining hosted gates. Rerunning produces no diff. This is the under-30-minute milestone; hosted provisioning and live canary are excluded from that promise.

### Nine-stage journey

| Stage | Required experience | Evidence or rescue |
|---|---|---|
| 1. Choose role/topology | README routes user, producer maintainer, or fleet operator and shows Codex standalone, plugin, Claude, both-target, and publisher constraints | Unsupported or duplicate topology is named before install |
| 2. Preflight | Read-only check covers GitHub CLI/auth, Python, client, repository identity, and local visibility | Typed prerequisite failure plus safe command |
| 3. Install and activate | One command, fresh session, fixture invocation, version/digest output | Separate Codex and Claude evidence cells |
| 4. Scaffold producer | init previews deterministic policy and caller; --apply is separate | Golden diff and idempotent rerun |
| 5. Local safe success | validate and doctor --local return LOCAL_READY | This is the 30-minute target |
| 6. Hosted provisioning | Doctor previews label, two environments/reviewers, permissions, secret, PR setting, protection, and canary | HOSTED_READY only after read-back |
| 7. Receipt to issue | Walkthrough shows proposal, public preview, both confirmations, issue identity, and reconciliation | No issue for no_issue or expired approval |
| 8. Issue to draft PR | Summary shows authorization ID; owner approves agent and publication; one draft appears | Typed stale/edit/replay/collision/unknown results |
| 9. Release and recovery | Human release, other-PC N-to-N+1, fresh activation, and bad-SHA drill | Last-compatible SHA/policy pair and post-rollback doctor |

### DX scorecard

| Dimension | Current | Target |
|---|---:|---:|
| Codex install and invocation | 7/10 | 9/10 |
| Claude another-PC journey | 5/10 | 8/10 |
| Producer onboarding | 2/10 | 9/10 |
| Fleet-owner recovery | 4/10 | 9/10 |
| Commands and output | 4/10 | 9/10 |
| Errors and rescue | 5/10 | 9/10 |
| Topology/discoverability | 4/10 | 9/10 |
| Evidence discipline | 9/10 | 10/10 |

### Normative CLI and output contract

The fleet CLI is skills/analyze-project-claims/scripts/managed_fleet.py:

- init previews deterministic policy/caller; mutation requires --apply.
- validate checks offline schema, pin, paths, workflow, and producer conformance.
- doctor --local checks local package/policy/caller state.
- doctor --repo OWNER/REPO checks hosted settings and canary readiness.
- pin-status reports approved, stale, incompatible, or advisory-revoked SHA.
- canary --dry-run shows the hosted plan without agent or write jobs.
- disable previews the caller/label/environment freeze; --apply is separate.
- rollback-plan --to-workflow-sha SHA previews a compatible rollback PR.
- reconcile-publication --authorization-id ID classifies branch, PR, and comment state.

Every JSON result contains schema_version, status, code, effect, changed, retryable, next_action, and docs. Exit 0 means ready/confirmed/safe no-op; 2 invalid or refused; 3 transient external failure; 4 unknown external outcome requiring reconciliation; 5 mutation failure requiring recovery. Human output summarizes the same fields without paths, credentials, arbitrary issue text, or raw arguments.

### Documentation deliverables

- docs/MANAGED_FLEET_QUICKSTART.md: 30-minute producer path, expected outputs, sample diff, LOCAL_READY.
- docs/MANAGED_FLEET_OPERATIONS.md: doctor, pin upgrade, freeze, lock, rollback, and uncertain publication.
- docs/MANAGED_REPAIR_WALKTHROUGH.md: receipt through confirmed issue, two approvals, validation, and draft PR.
- docs/MULTI_AGENT_INSTALL_TOPOLOGY.md: Codex, plugin, Claude, both-target, project, publisher, pinned, modified, and duplicate states.
- docs/MANAGED_FLEET_SUPPORT_MATRIX.md: repository, OS, host, authority, updater, workflow SHA, canary, observation, and date.
- Rewrite GITHUB_AGENT_MAINTAINER_GUIDE.md for policy/caller adoption and label copying as unsupported legacy.
- Replace legacy setup in PUBLISHING.md with conformance, environment, canary, rollback, and exact-pin gates.
- Add fleet maintainer links/gates to each producer README/PUBLISHING file, a packaged updater rescue pointer, and another-PC receipt template.

### DX test additions

- Deterministic/idempotent scaffold tests for all producers and one common conformance suite.
- CLI/error snapshots with correct producer, typed code, effect, changed, retry, safe command, and docs.
- Doctor matrix for unprotected environments, stale pin, bad schema, PR setting, ambiguous/modified/plugin install, offline state, and failed canary.
- Cross-document test rejecting active copy instructions, fleet-token assumptions, or run-ID branch names.
- PowerShell/POSIX smoke for every documented read-only command.
- Cross-agent topology and another-PC Claude cells for install, discovery, invocation, replacement, and activation.
- Hosted issue-to-draft E2E with both approvals and replay/edit/relabel/stale/uncertain cases.
- Bad-pin drill proving disablement and compatible restoration without executing the bad workflow.

## Review completion summary

- CEO: SELECTIVE EXPANSION; both voices chose the full-SHA reusable workflow plus closed local policy.
- Visual design: skipped because no UI is in scope.
- Engineering: CONDITIONAL GO; all current blockers are explicit implementation/test requirements.
- DX: CONDITIONAL GO; onboarding, topology, command, and recovery surfaces are release deliverables.
- Recommended user challenges resolved: two approvals; onboard three but canary method and venue before server; rebuild evidence after implementation.
- Preliminary map candidates are superseded and must not be accepted.

## Review readiness dashboard

| Area | Readiness | Remaining gate |
|---|---|---|
| Product objective and scope | Ready | User approval |
| Architecture and trust boundaries | Ready for implementation | Implement and verify |
| Engineering interfaces and test plan | Ready for implementation | Implement and run hosted canaries |
| Developer experience contract | Ready for implementation | Build docs/CLI and smoke commands |
| Evidence-map acceptance | Not ready | Rebuild post-implementation exact candidates |
| Publication and other-PC activation | Not observed | Complete remote/public release gates |

## Plan file review report

- Plan file: docs/MANAGED_SKILL_LIFECYCLE_V081_PLAN.md
- Restore point: C:\Users\chois\.gstack\projects\analyze-project-claims\feature-cross-skill-managed-lifecycle-v081-autoplan-restore-20260820-224822.md
- Engineering test plan: C:\Users\chois\.gstack\projects\Ian-Tseng-analyze-project-claims\chois-featurecross-skill-managed-lifecycle-v081-eng-review-test-plan-20260820-232924.md
- Required CEO, engineering, DX, scope, failure, implementation, evidence, and final-gate sections: present.
- Visual-design phase: not applicable because no UI is in scope.
- Markdown whitespace check: passed.
- Phase task JSONL: skipped as required because jq is unavailable; no hand-written substitute was created.
- Implementation changes, tests, map acceptance, commits, pushes, and publication: intentionally not started by this plan-review turn.

## GSTACK REVIEW REPORT

### Runs

| Phase | Outside voice | Codex voice | Status |
|---|---|---|---|
| CEO | Independent fresh-context agent (Claude unavailable) | Codex CLI | Complete |
| Visual design | Not applicable | Not applicable | Skipped |
| Engineering | Independent fresh-context agent | Codex CLI | Complete |
| Developer experience | Independent fresh-context agent | Codex CLI | Complete |

### Status and findings

- Architecture: full-SHA reusable GitHub Cloud workflow, central $/ helpers, closed producer policy, thin caller.
- Trust: managed replacement, supported-invocation claim, two protected environments, immutable authorization, credential-free candidate, isolated validation, deterministic reconciliation, caller rollback.
- Rollout: onboard all three; method and venue are canaries; server repair stays disabled until both pass.
- DX gate: scaffold, doctor, quickstart, topology matrix, walkthrough, recovery runbook, and output contract.
- Evidence gate: rebuild after implementation, accept only new exact candidates, reconcile unchanged, append fresh records.

VERDICT: APPROVED — implement the complete recommended architecture, then rebuild and accept the three exact matching candidates.

NO UNRESOLVED DECISIONS
