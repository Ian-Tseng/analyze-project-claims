# Analyze Project Claims Quality Loop

The quality loop lets compatible Ian-Tseng-managed skills produce a bounded
receipt that `analyze-project-claims` turns into one local, deduplicated review
proposal. It does not observe arbitrary skills, inspect transcripts, edit a
running package, or publish automatically.

## Trust boundary

```text
compatible producer
  -> content-free SkillOutcomeReceipt
  -> explicit handoff OR trusted Codex Stop adapter
  -> private local receipt store
  -> one proposal per receipt digest and analyzer version
  -> exact contribution preview
  -> per-submission approval
  -> separate public-visibility confirmation
  -> Ian-Tseng owner triage and agent-ready label
  -> isolated map-pending draft PR
  -> owner component-map acceptance
  -> CI, review, release, installed replacement, fresh invocation
```

Every arrow after the local proposal is a separate gate. Update consent does
not authorize contributions, analytics, reports, releases, or attachments.

## Five-minute local fixture

With Python 3 available:

```powershell
$state = Join-Path $env:TEMP "analyze-project-claims-quality-fixture"
py -3 skills\analyze-project-claims\scripts\skill_quality_loop.py `
  --format json --state-dir $state conformance
```

Expected bounded result:

```text
QUALITY_PROPOSAL_READY
proposal: quality-proposal-<24 hex>
replay_deduplicated: true
outbound: NONE
```

The target from producer completion to this result is p50 at most two minutes
and p95 under five minutes on a warm supported host. This target must not be
reported as achieved until measured on released installs.

## Local commands

Put global options before the verb:

```powershell
py -3 <skill-root>\scripts\skill_quality_loop.py --format json status
py -3 <skill-root>\scripts\skill_quality_loop.py --format json doctor
py -3 <skill-root>\scripts\skill_quality_loop.py --format json validate --marker <marker>
py -3 <skill-root>\scripts\skill_quality_loop.py --format json consume --marker <marker>
py -3 <skill-root>\scripts\skill_quality_loop.py --format json consume
py -3 <skill-root>\scripts\skill_quality_loop.py --format json proposal-show --proposal-id <id>
py -3 <skill-root>\scripts\skill_quality_loop.py --format json proposal-dismiss --proposal-id <id>
```

With no marker, `consume` uses the oldest locally pending compatible receipt.
State is machine-local and is never synchronized. Standalone state uses the OS
state directory; the Codex plugin uses `PLUGIN_DATA/skill-quality`. Expired
pending receipts and terminal receipt records are reclaimed. Active proposals
retain bounded backpressure; dismissed proposals are the first records
reclaimed when capacity is needed.

## Codex plugin adapter

The repository root is one plugin package and contains the canonical skill
tree plus `hooks/hooks.json`. There is no duplicated skill copy. Add the
repository marketplace and install the plugin using the current Codex plugin
workflow, then review the exact hook in `/hooks` before trusting it.

The adapter:

- uses only official `last_assistant_message`, `session_id`, `turn_id`, and
  `stop_hook_active` fields;
- extracts only an exact final-line receipt marker;
- never reads `transcript_path`, project files, prompts, tool data, or network;
- persists only the receipt plus the local host session/turn envelope;
- has a five-second process timeout and no semantic analysis in the hook;
- requests at most one continuation for an original session/turn;
- rejects analyzer-origin and depth-one recursion.

Codex may run multiple matching hooks concurrently. Another hook can veto the
continuation, and model routing may not invoke this named skill. Therefore the
adapter claim is **at most one continuation request**, not exactly one named
skill invocation. The receipt remains available for explicit `consume`.

## Proposal and contribution

Local proposal fields remain enum and package identity only. To prepare a
contribution:

```powershell
py -3 <skill-root>\scripts\skill_quality_loop.py --format json `
  contribution-preview --proposal-id <id>
```

The preview sends nothing. Inspect its exact draft, approval ID, and destination.
Submission requires that exact ID and explicit approval:

```powershell
py -3 <skill-root>\scripts\skill_quality_loop.py --format json `
  contribution-submit --draft <draft.json> --approve <approval-id> --approved
```

The destination is derived, not supplied: a receipt from repository
`<producer-repository>` can target only
`Ian-Tseng/<producer-repository>`. The fixed owner boundary prevents routing
to another GitHub account. If that repository is public, the first attempt
stops with `PUBLIC_ISSUE_APPROVAL_REQUIRED`. Only after confirming the exact
public draft may the user repeat with `--allow-public-issue`. The issue
contains no files, patches, project content, paths, prompts, logs, findings,
or attachments.

The exact approval expires after 24 hours. A contribution ID is one-use in
local state, so replay returns the first issue instead of creating another.
If GitHub times out, errors, or returns an unexpected response after creation
begins, the state becomes `UNKNOWN`; reconcile the contribution ID on GitHub
before retrying.

Creating an issue does not itself run a maintainer. Only `Ian-Tseng` can
review it and, where the destination repository has the protected maintainer
workflow installed, add `agent-ready`. That workflow may produce only a
map-pending draft PR; it cannot edit `validation/`, accept a map, merge,
release, close the issue, or update installed copies. Without that workflow,
the label is only an owner triage signal.

## Update authority

Use exactly one authority for each installed copy:

| Installation | Authority |
|---|---|
| Codex plugin bundle | Codex plugin manager |
| Clean tracked standalone user copy with verified source, tree, version, path, and manifest | GitHub CLI updater after consent |
| Pinned, project, manual, or edited copy | User/manual |
| Two visible same-name standalone copies | Unresolved; no automatic update |

Diagnose without changing anything:

```powershell
py -3 <skill-root>\scripts\update_policy.py --format json doctor
```

`GITHUB_CLI_AUTHORITY` is returned only after the running copy and package
manifest pass the same identity checks used by update enablement. The doctor
always lists the running package even when GitHub CLI does not track it.

The maintenance route may run after every substantive skill invocation, but a
successful remote update check still has a 24-hour lease. Installed replacement
becomes active on a fresh invocation, never the current one.

## Error contracts

Every CLI error reports problem, cause/code, effect, fix, retry, safety, and
documentation.

### `NO_COMPATIBLE_RECEIPT`

No analysis ran because no valid unexpired receipt was available. Run a
compatible producer or a normal project audit, then retry. No transcript,
project file, or network endpoint was inspected.

### `RECEIPT_SCHEMA_VIOLATION`

The receipt failed the closed schema. Rejected values are not echoed or used.
Update the producer and validate locally. No proposal or outbound draft was
created.

### `CONTINUATION_NOT_OBSERVED`

The trusted adapter persisted a receipt but the host did not produce the
requested analyzer continuation, possibly because of routing, timeout, or
another hook. Run explicit `consume`; do not emit another receipt solely to
retry.

### `UPDATE_AUTHORITY_CONFLICT`

More than one visible same-name installation makes update-by-name unsafe. Run
the update doctor, keep one authority, and retry. No copy is removed,
overwritten, unpinned, or changed automatically.

### `PUBLIC_ISSUE_APPROVAL_REQUIRED`

The exact bounded contribution would be public. Review the preview and give a
second, draft-specific confirmation or keep it local.

## Evidence boundary

Unit and conformance tests prove only their fixtures. A validated plugin
package does not prove live hook continuation. GitHub CLI installation does not
prove Claude discovery or invocation. A draft PR does not prove resolution. A
release does not prove installed replacement or fresh activation.
