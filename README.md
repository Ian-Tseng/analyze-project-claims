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

The managed installation requires GitHub CLI 2.90.0 or later.
The canonical owner is `Ian-Tseng`. For a private repository, the installing account must already have access:

```powershell
gh skill install Ian-Tseng/analyze-project-claims `
  skill/analyze-project-claims/SKILL.md `
  --agent codex `
  --scope user
```

The exact `SKILL.md` path is required because the installable package currently
lives in the repository's `skill/` directory. `gh skill` is in public preview.

For a manual installation without managed updates:

```powershell
Copy-Item -Recurse -Force `
  .\skill\analyze-project-claims `
  "$env:USERPROFILE\.codex\skills\analyze-project-claims"
```

Manual copies are not eligible for automatic upgrades.

## Quickstart

Open the project you want to inspect and ask Codex:

```text
Use $analyze-project-claims to audit this repository's claims, evidence,
lifecycle states, contradictions, and next validation gate.
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

An eligible GitHub CLI installation asks once whether to enable updates, after
the first substantive audit is complete. Nothing is checked or changed before
you choose.

Say one of:

- `enable automatic updates`;
- `notify me about updates`;
- `disable updates`;
- `check for updates now`;
- `show update status`.

With `auto` enabled, the skill checks at most once every 24 hours after the
current task finishes. GitHub CLI performs the replacement; the updater verifies
the source, path, version, Git tree identity, and package manifest. The current
invocation keeps its starting version, and the next invocation loads a verified
update.

Automatic replacement applies only to one clean, unpinned, user-scope install
tracked by GitHub CLI. Pinned and project-scope installs become notify-only.
Duplicate, locally edited, manually copied, and plugin-hosted copies are not
automatically replaced. The updater never forces an overwrite or removes a pin.

The local policy record contains only the selected mode, hashed source/install
binding, timestamps, suspension state, and last outcome. No project content,
claims, errors, or telemetry are sent to a database.

## Formal audit records

Most users can stop after the agent's audit response. Formal reviews can also
create two machine-readable artifacts:

- a component map describing what is in scope and checkable;
- an append-only scan record describing what was actually tested and learned.

The map has an explicit candidate and acceptance lifecycle. Existing accepted
maps are never replaced implicitly. Scan records bind their evidence to the
exact skill bytes and keep check status separate from claim status.

Start with these files:

- `skill/analyze-project-claims/assets/component-map-observation.template.json`;
- `skill/analyze-project-claims/references/component-map-observation.schema.json`;
- `skill/analyze-project-claims/assets/scan-record.template.json`;
- `skill/analyze-project-claims/references/scan-record.schema.json`.

Create or reconcile a component map:

```powershell
py -3 .\skill\analyze-project-claims\scripts\reconcile_component_map.py reconcile `
  --observation .\component-map-observation.json `
  --map-root .\.claim-audit\component-map `
  --project-root .
```

After human review, accept the exact returned candidate:

```powershell
py -3 .\skill\analyze-project-claims\scripts\reconcile_component_map.py accept `
  --candidate .\.claim-audit\component-map\candidates\<candidate>.json `
  --map-root .\.claim-audit\component-map
```

Persist a validated append-only scan record:

```powershell
py -3 .\skill\analyze-project-claims\scripts\record_scan.py `
  --record .\examples\scan-input.example.json `
  --log-dir .\validation\history
```

See `validation/README.md` for current and historical artifact authority.

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

## Maintainers

Read [PUBLISHING.md](PUBLISHING.md) for owner setup, license and citation gates,
manifest rebuilding, GitHub upload, `gh skill publish`, and public install/update
smoke tests.

Version `0.4.0` adds consent-gated automatic upgrades. `VERSION`, package
metadata, the package manifest, and citation metadata must remain synchronized.

## Citation and license

`CITATION.cff.template` remains a template because the public owner, author
identity, license, and release DOI have not been supplied. Complete it and
rename it to `CITATION.cff` before the identified public release.

No software license has been selected. Add an author-approved `LICENSE` before
describing this repository as open source. Publishing code without a license
does not grant general reuse rights.
