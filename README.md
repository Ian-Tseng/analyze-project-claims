# Analyze Project Claims

Audit a research or engineering project without confusing completed work with
proven results.

`analyze-project-claims` helps an AI agent trace objectives, claims, evidence,
counterevidence, dependencies, lifecycle states, risks, and decisions across a
repository. It finds contradictions, states the strongest claim the available
evidence supports, and recommends the smallest useful next check.

Use it when code, reports, experiment artifacts, tables, and status documents
may disagree, or when a project needs a defensible answer to: what do we
actually know?
## What it checks

- source-of-truth and authority boundaries;
- claims with same-scope evidence and counterevidence;
- runner, audit, scientific, and acceptance states kept separate;
- completed experiments and proof that artifacts were actually consumed;
- contradictions across code, configuration, artifacts, monitors, tables, and
  prose;
- provenance, split, leakage, and publication boundaries;
- the smallest evidence-producing next action.

## Install

### Codex

A managed Codex installation requires GitHub CLI 2.90.0 or later. Install the
public package from its canonical owner, `Ian-Tseng`:

```powershell
gh skill install Ian-Tseng/analyze-project-claims `
  skills/analyze-project-claims/SKILL.md `
  --agent codex `
  --scope user
```

The canonical path makes the package unambiguous and lets `gh skill update`
rediscover it. `gh skill` is in public preview.

For an unmanaged Codex copy:

```powershell
Copy-Item -Recurse -Force `
  .\skills\analyze-project-claims `
  "$env:USERPROFILE\.codex\skills\analyze-project-claims"
```

### Claude Code

Claude Code uses the same
[Agent Skills package](https://code.claude.com/docs/en/skills). Install it from
the canonical source as a GitHub CLI-tracked user skill:

```powershell
gh skill install Ian-Tseng/analyze-project-claims `
  skills/analyze-project-claims/SKILL.md `
  --agent claude-code `
  --scope user
```

GitHub CLI records it under `~/.claude/skills` so `gh skill list` and `gh skill
update` can rediscover it. A direct copy is an unmanaged fallback and cannot
receive managed updates.

## Quickstart

Open the project you want to inspect and invoke the installed skill.

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

For a narrower check:

```text
Use $analyze-project-claims to verify whether the reported experiment is
actually complete and whether its result is strong enough for the stated claim.
```

The response leads with the conclusion and normally includes:

```text
Overall conclusion

finding | evidence | status | safest interpretation | required repair

Strongest safe claim
Scientific and publication boundary
Recommended next action
Unresolved uncertainty
```

The skill does not silently turn 'unknown,' 'failed,' or 'not tested' into a
pass.

See the [lifecycle receipt guide](docs/LIFECYCLE_RECEIPT_GUIDE.md).

## Example

If a status document says an experiment is complete but the result table was
generated from an older run, the skill should report something like:

```text
Overall conclusion: The workflow completed, but the reported scientific result
is not established from the current run.

Finding: The active result table does not consume the current run artifact.
Status: Contradicted.
Safest interpretation: Execution completed; scientific success remains
untested for the current configuration.
Required repair: Regenerate the table from the current artifact and record its
identity before making the result claim.
```

This is the core product boundary: process completion, structural validation,
scientific success, and publication eligibility are separate conclusions.

## Automatic updates

This section applies only to eligible GitHub CLI-tracked standalone
installations. Such an installation asks once whether to enable updates after
the first substantive audit. Nothing is checked or changed before you choose.

Live replacement has been validated on Codex. The Claude Code path has verified
install, listing, manifest, and update dry-run evidence, but not yet live Claude
discovery, invocation, or replacement evidence.

Say one of:

- `enable automatic updates`;
- `notify me about updates`;
- `disable updates`;
- `check for updates now`;
- `show update status`.

With `auto` enabled, a successful check starts a 24-hour lease after the
current task finishes. A transient failure may retry no sooner than one hour
on a later invocation. GitHub CLI performs the replacement; the updater
verifies the source, path, version, Git tree identity, and package manifest.
The current invocation keeps its starting version, and the next invocation
loads a verified update.

Automatic replacement applies only to one clean, unpinned, user-scope install
tracked by GitHub CLI. Pinned and project-scope installs become notify-only.
Duplicate, locally edited, manually copied, and plugin-hosted copies are not
automatically replaced. The updater never forces an overwrite or removes a pin.

The update policy stores only its mode, hashed install binding, timestamps,
suspension state, and last outcome. Update consent does not grant reporting
consent.

## Optional installation analytics

The repository contains an opt-in reference client and private owner API for
counting unique consenting activated installations by version. This is not a
download count or a count of unique people. No public analytics endpoint is
currently bundled or claimed as deployed, so installing or using the skill
does not send analytics by default.

The user must enable a reviewed owner endpoint and later run a check-in before
the first bounded event is sent. Update and problem-report consent remain
separate. Read [Privacy-Bounded Installation Analytics](docs/INSTALLATION_ANALYTICS.md)
for the exact fields, user controls, owner deployment, aggregate query, erasure,
retention, and evidence limits.

## Report an internal tool problem

When the tool itself fails, the skill can prepare a local preview and ask
before sending it. Project-audit findings are never reported.

Say `report this internal tool problem`, `enable minimal automatic problem
reports`, `disable problem reporting`, or `show problem-reporting status`.

GitHub delivery checks repository visibility. A public issue requires approval
of the exact preview plus a separate public-issue confirmation. Automatic
reports require the optional private owner API. Report suspected vulnerabilities
through [SECURITY.md](SECURITY.md), never through a public issue.

The fixed schema excludes project content, raw logs, prompts, attachments, and
credentials; path- and secret-like text is rejected locally. Reports cannot
install code. The owner reviews, tests, and publishes a release. Only a
separately enabled updater can install it on later use.

Read [Internal Problem Reporting](docs/PROBLEM_REPORTING.md) for the reusable
architecture, data contract, owner workflow, API, retention, and deletion.
Maintainers can optionally use the owner-gated
[Agent Maintainer](docs/AGENT_MAINTAINER.md) to turn an exact disclosed public
report into a tested draft pull request; it never merges or releases by itself.
For another repository, use the
[reusable agent-maintainer guide](docs/GITHUB_AGENT_MAINTAINER_GUIDE.md).

## Formal audit records

Formal reviews can persist an accepted component map and an append-only v2
evidence-bound audit record. Material claims use stable component/element IDs;
evidence uses exact source and selection digests; explicit bindings connect
them. Markdown reports are derived views, not a second authority.

Start with:

- `skills/analyze-project-claims/assets/component-map-observation.template.json`;
- `skills/analyze-project-claims/references/component-map-observation.schema.json`;
- `skills/analyze-project-claims/assets/scan-record-v2.template.json`;
- `skills/analyze-project-claims/references/scan-record-v2.schema.json`.

Verify the embedded engine, then reconcile and explicitly accept a map:

```powershell
py -3 .\skills\analyze-project-claims\scripts\reconcile_component_map.py verify-self
py -3 .\skills\analyze-project-claims\scripts\reconcile_component_map.py reconcile `
  --observation .\component-map-observation.json --map-root .\.claim-audit\component-map --project-root .
py -3 .\skills\analyze-project-claims\scripts\reconcile_component_map.py accept `
  --candidate .\.claim-audit\component-map\candidates\<candidate>.json --map-root .\.claim-audit\component-map
```

Validate before the append-only write:

```powershell
py -3 .\skills\analyze-project-claims\scripts\record_scan.py init `
  --map-root .\.claim-audit\component-map --project-root . --output .\scan-input.json
py -3 .\skills\analyze-project-claims\scripts\record_scan.py validate `
  --record .\scan-input.json --map-root .\.claim-audit\component-map --project-root .
py -3 .\skills\analyze-project-claims\scripts\record_scan.py append `
  --record .\scan-input.json --map-root .\.claim-audit\component-map --project-root . `
  --log-dir .\validation\history --report-dir .\validation\reports
```

`executed_test` must cite a persisted result or receipt, not test source;
`not_tested` is context-only. Append and verify recompute local evidence.
External evidence is not fetched and stays unverifiable without a SHA-256 digest
or full lowercase 40-/64-hexadecimal object ID. Legacy v1 records remain
readable as `legacy_unbound`. See the
[evidence-bound record guide](skills/analyze-project-claims/references/evidence-bound-audit-records.md)
and [validation authority](validation/README.md).

## Evidence and limitations

The package structure, deterministic helpers, update policy, and regression
tests are validated. The workflow has also been used on one outcome-known RAG
project, where it found and supported repair of lifecycle, provenance,
terminology, and claim-boundary inconsistencies.

That does not establish general reliability across projects, domains, agents,
or models, and this skill does not claim to improve retrieval or generation
quality. Cross-project human evaluation remains incomplete.

The detailed evaluation protocol, calibration workflow, natural-project pilot,
schemas, and claim boundaries live in [evaluation/README.md](evaluation/README.md).
They remain public for transparency without blocking the main user journey.

## Validation

The public package uses only the Python standard library for its mapper,
recorder, updater, and tests:

```powershell
py -3 -m unittest discover -s tests -v
```

Use `python3` instead of `py -3` on macOS or Linux. A passing suite validates
the tested software contracts; it does not establish scientific benefit or
cross-project reliability.

## Maintainer and release guidance

Read [PUBLISHING.md](PUBLISHING.md) for owner setup, license and citation gates,
manifest rebuilding, GitHub upload, `gh skill publish`, and public install/update
smoke tests.

For the reusable design and release procedure, read
[How to Build Safe Managed Updates for a GitHub Skill](docs/MANAGED_SKILL_UPDATE_GUIDE.md).
For the exact v0.4.1 to v0.4.2 validation record and the limits of that evidence,
read [Managed Update End-to-End Evidence Log](docs/MANAGED_UPDATE_E2E_LOG.md).

For a reusable cross-agent validation procedure, read
[How to Validate a GitHub Skill Across Codex and Claude Code](docs/MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md).
The current Claude-targeted result and its runtime limit are in the
[Claude Code E2E Evidence Log](docs/CLAUDE_CODE_E2E_LOG.md).

`VERSION`, package metadata, the package manifest, and citation metadata must
remain synchronized for every release.

## Release history

See the repository's versioned changes and published artifacts on
[GitHub Releases](https://github.com/Ian-Tseng/analyze-project-claims/releases).

## Citation and license

Citation metadata is in [CITATION.cff](CITATION.cff). The software is available
under the [MIT License](LICENSE).
