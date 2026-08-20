# Installed Skill Quality Loop Contract

Read this reference when consuming or emitting a `SkillOutcomeReceipt`, showing
or dismissing a local quality proposal, diagnosing the Codex adapter, or
preparing an owner contribution.

## Promise and boundary

Compatible Ian-Tseng-managed skills may emit a content-free v1 receipt. This
skill validates it and creates one local proposal per receipt digest and
analyzer version. It does not observe arbitrary skills, parse transcripts,
authenticate producer claims, edit a running package, or publish automatically.

The optional Codex plugin `Stop` hook can request at most one continuation for
an original session/turn. It cannot guarantee one named-skill invocation:
matching hooks run concurrently, another hook may veto continuation, and model
routing is not deterministic. A persisted receipt remains available for the
portable explicit path.

## Receipt contract

Use `skill-outcome-receipt.schema.json`. Unknown fields fail closed. The
receipt permits only version and UUID identity, producer-declared owner/repo/
skill/version/package digest, outcome and signal enums, timestamps, bounded
causal depth, optional prior digest, `action_performed: false`, and its
canonical digest.

`no_issue` must pair with `requested_action: none`; every other signal must
pair with `analyze_quality`. A no-action receipt never requests a Stop
continuation, creates a proposal, or becomes contribution-eligible. Creation
time may be at most five minutes in the future and lifetime is at most 24
hours.

Reject free text, prompts, transcripts, paths, URLs, logs, tool data, project
findings, errors, diffs, patches, tokens, credentials, and attachments. Do not
fall back to inspecting the project or transcript.

## Deterministic commands

Use global options before the verb:

```text
<python-3> scripts/skill_quality_loop.py --format json status
<python-3> scripts/skill_quality_loop.py --format json doctor
<python-3> scripts/skill_quality_loop.py --format json validate --marker <marker>
<python-3> scripts/skill_quality_loop.py --format json consume --marker <marker>
<python-3> scripts/skill_quality_loop.py --format json consume
<python-3> scripts/skill_quality_loop.py --format json proposal-show --proposal-id <id>
<python-3> scripts/skill_quality_loop.py --format json proposal-dismiss --proposal-id <id>
<python-3> scripts/skill_quality_loop.py --format json --state-dir <disposable-dir> conformance
```

With no marker, `consume` selects the oldest pending compatible receipt. Keep
state machine-local. Never sync receipts, proposals, or consents. Expired and
terminal receipt records are reclaimed. Active proposals apply backpressure at
the bounded limit; dismissing proposals makes bounded capacity reusable.

## Contribution

Preview sends nothing:

```text
<python-3> scripts/skill_quality_loop.py --format json contribution-preview --proposal-id <id>
```

Submit only after the user approves that exact draft and approval ID:

```text
<python-3> scripts/skill_quality_loop.py --format json contribution-submit \
  --draft <draft.json> --approve <approval-id> --approved
```

The destination is derived from the receipt and fixed to
`Ian-Tseng/<producer-repository>`; it cannot route to another owner. On
`PUBLIC_ISSUE_APPROVAL_REQUIRED`, show the exact preview and obtain a second
draft-specific confirmation before adding `--allow-public-issue`. Never add
the flag automatically.

Approval expires after 24 hours and each contribution ID is one-use. A
`CONTRIBUTION_OUTCOME_UNKNOWN` result means GitHub may have created the issue:
search GitHub for the exact contribution ID and do not retry until reconciled.

The contribution is enum and package identity only. It excludes files,
patches, project content, paths, prompts, logs, findings, and attachments. Only
`Ian-Tseng` may later add `agent-ready`. Where the destination repository
has the protected maintainer workflow installed, that authorizes one isolated
map-pending draft attempt; otherwise it is only an owner triage signal. It
never authorizes map acceptance, merge, release, closure, or installed update.

## Errors

Preserve the substantive skill result. Return the CLI's complete problem,
cause, effect, fix, retry, safety, and docs fields. Common codes are:

- `NO_COMPATIBLE_RECEIPT`: run a producer or normal audit, then retry;
- `RECEIPT_SCHEMA_VIOLATION`: update and locally validate the producer;
- `RECEIPT_EXPIRED`: generate a new receipt;
- `RECEIPT_FUTURE_DATED`: correct the producer clock and generate a new receipt;
- `RECEIPT_BUSY`: wait for the lease;
- `CONTRIBUTION_OUTCOME_UNKNOWN`: reconcile the contribution ID on GitHub and do not retry;
- `PUBLIC_ISSUE_APPROVAL_REQUIRED`: keep local or confirm the exact public draft;
- `UPDATE_AUTHORITY_CONFLICT`: run `update_policy.py --format json doctor` and
  keep one authority.
