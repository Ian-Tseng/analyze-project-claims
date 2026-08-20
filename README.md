# Analyze Project Claims

Audit a research or engineering project without confusing completed work with
proven results.

`analyze-project-claims` traces objectives, claims, evidence, counterevidence,
dependencies, lifecycle states, risks, and decisions across a repository. It
finds contradictions, states the strongest claim the evidence supports, and
recommends the smallest useful next check.

## What it checks

- authority and source-of-truth boundaries;
- same-scope evidence and counterevidence;
- runner, audit, scientific, and acceptance states kept separate;
- proof that reported pipelines consumed the cited artifacts;
- contradictions across code, configuration, monitors, tables, and prose;
- provenance, split, leakage, and publication boundaries.

## Install

### Codex standalone skill

For a GitHub CLI-tracked standalone install:

```powershell
gh skill install Ian-Tseng/analyze-project-claims skills/analyze-project-claims/SKILL.md --agent codex --scope user
```

This needs GitHub CLI 2.90.0 or later. The canonical path lets `gh skill
update` rediscover the package.

### Codex plugin with bounded handoff

Choose this instead of the standalone install when you want the optional
`Stop` receipt hook:

```powershell
codex plugin marketplace add Ian-Tseng/analyze-project-claims --ref v0.8.0
codex plugin add analyze-project-claims@ian-tseng-analyze-project-claims
```

Do not install both copies under the same visible name. Review the exact hook
before trusting it. The plugin manager owns updates. The hook can request at
most one continuation, but routing is not guaranteed and live continuation is
not yet claimed. Explicit `consume` is the portable fallback.

### Claude Code

Claude Code uses the same
[Agent Skills package](https://code.claude.com/docs/en/skills):

```powershell
gh skill install Ian-Tseng/analyze-project-claims skills/analyze-project-claims/SKILL.md --agent claude-code --scope user
```

This proves managed distribution only until Claude `/skills` discovery and
invocation are observed.

## Quickstart

In Codex:

```text
Use $analyze-project-claims to audit this repository's claims, evidence,
lifecycle states, contradictions, and next validation gate.
```

In Claude Code:

```text
/analyze-project-claims audit this repository's claims, evidence, lifecycle
states, contradictions, and next validation gate.
```

A typical response includes the conclusion, an inconsistency table, strongest
safe claim, scientific and publication boundary, next action, and unresolved
uncertainty. The skill never silently turns `unknown`, `failed`, or
`not_tested` into a pass. See the
[lifecycle receipt guide](docs/LIFECYCLE_RECEIPT_GUIDE.md).

## Example

If a status document says an experiment is complete but its result table came
from an older run, the safe conclusion is:

```text
Execution completed, but the current scientific result is untested.
Regenerate the table from the current artifact and bind its identity before
making the result claim.
```

Process completion, structural validity, scientific success, and publication
eligibility are separate conclusions.

## Optional skill-quality loop

Compatible Ian-Tseng-managed skills can end with a content-free
`SkillOutcomeReceipt`. It permits enum and package identity only: no project
text, prompt, transcript, path, log, finding, attachment, or credential.

```powershell
py -3 .\skills\analyze-project-claims\scripts\skill_quality_loop.py --format json consume --marker "<exact-marker>"
py -3 .\skills\analyze-project-claims\scripts\skill_quality_loop.py --format json --state-dir .\.quality-loop-smoke conformance
```

Replay returns the same proposal ID. Conformance must report
`QUALITY_PROPOSAL_READY`, `replay_deduplicated: true`, and `outbound: NONE`.
No issue, edit, update, or release is authorized. Read
[Skill Quality Loop](docs/SKILL_QUALITY_LOOP.md), the
[receipt contract](docs/SKILL_OUTCOME_RECEIPT.md), and the
[reusable design guide](docs/SAFE_MANAGED_SKILL_QUALITY_LOOP.md).

## Automatic updates

Eligible standalone installs ask once after the first audit. Nothing is
checked or changed before consent. Say:

- `enable automatic updates`;
- `notify me about updates`;
- `disable updates`;
- `check for updates now`;
- `show update status`;
- `diagnose update authority`.

Checks use a 24-hour success lease and one-hour transient retry. Replacement
requires one clean, unpinned user install with verified source, tree, version,
and manifest; it activates next use. Pinned, project, duplicate, edited,
manual, and plugin copies are never blindly replaced. The doctor lists
competing copies without deleting them. Update, reporting, analytics, and
contribution consent remain separate.

## Optional installation analytics

The opt-in reference client counts unique consenting activated installations,
not downloads or people. No public endpoint is claimed, so using the skill
does not send analytics by default. Enabling an endpoint and sending a later
check-in are separate. See
[Privacy-Bounded Installation Analytics](docs/INSTALLATION_ANALYTICS.md).

## Report an internal tool problem

Internal failures can create a local bounded preview; project findings are
never reports. Public submission needs exact-preview approval plus a second
visibility confirmation. Automatic reports require a private owner API;
security issues use [SECURITY.md](SECURITY.md).

The schema excludes project content, logs, prompts, paths, attachments, and
credentials. The owner-gated [Agent Maintainer](docs/AGENT_MAINTAINER.md) may
create one map-pending draft from an exact report or enum-only contribution; it
cannot accept, merge, release, close, or update. See
[Internal Problem Reporting](docs/PROBLEM_REPORTING.md) and the
[reusable maintainer guide](docs/GITHUB_AGENT_MAINTAINER_GUIDE.md).

## Formal audit records

Formal reviews use an explicitly accepted component map and append-only v2
claim-to-evidence records. Start with:

- `skills/analyze-project-claims/assets/component-map-observation.template.json`;
- `skills/analyze-project-claims/references/component-map-observation.schema.json`;
- `skills/analyze-project-claims/assets/scan-record-v2.template.json`;
- `skills/analyze-project-claims/references/scan-record-v2.schema.json`.

Verify the embedded engine, reconcile and explicitly accept the exact
candidate, then require a second unchanged reconciliation and preflight before
append. `executed_test` cites persisted output, not test source. External
evidence is never fetched implicitly. Markdown is derived, not authority. See
the [evidence-bound record guide](skills/analyze-project-claims/references/evidence-bound-audit-records.md)
and [validation authority](validation/README.md).

## Evidence and limitations

The package structure, deterministic helpers, update policy, and regression
tests are validated. One outcome-known RAG-project exercise found lifecycle,
provenance, terminology, and claim-boundary inconsistencies. That does not
establish reliability across projects, domains, agents, or models, or claim
improved retrieval or generation quality.

The evaluation protocol, calibration flow, natural-project pilot, schemas, and
boundaries are in [evaluation/README.md](evaluation/README.md).

## Validation

The package uses only the Python standard library:

```powershell
py -3 -m unittest discover -s tests -v
```

A pass establishes only the tested contracts.

## Maintainer and release guidance

Read [PUBLISHING.md](PUBLISHING.md) for identity, map, manifest, CI, publication,
and public install/update gates. Reusable procedures and dated evidence:

- [Safe Managed Updates](docs/MANAGED_SKILL_UPDATE_GUIDE.md)
- [Managed Update E2E Log](docs/MANAGED_UPDATE_E2E_LOG.md)
- [Cross-Agent Validation](docs/MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md)
- [Claude Code E2E Log](docs/CLAUDE_CODE_E2E_LOG.md)
- [Other-PC Claude Checklist](docs/CLAUDE_CODE_OTHER_PC_CHECKLIST.md)
- [Codex Plugin E2E Log](docs/CODEX_PLUGIN_E2E_LOG.md)

`VERSION`, citation, package, plugin, manifest, and accepted-map identities must
remain synchronized. Historical release artifacts are on
[GitHub Releases](https://github.com/Ian-Tseng/analyze-project-claims/releases).

## Citation and license

See [CITATION.cff](CITATION.cff) and the [MIT License](LICENSE).
