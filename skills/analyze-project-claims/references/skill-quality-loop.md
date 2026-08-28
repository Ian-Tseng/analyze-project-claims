# Installed Skill Quality Loop Contract

Read this reference when consuming or emitting a `SkillOutcomeReceipt`, showing
or dismissing a local quality proposal, diagnosing the Codex adapter, or
preparing an owner contribution.

## Promise and boundary

Compatible Ian-Tseng-managed skills may emit a content-free v2 receipt; exact
v1 receipts remain readable. This skill validates it and creates one local
intake proposal per exact receipt digest. Analyzer versions create child
analysis revisions, not duplicate proposals. It does not observe arbitrary skills, parse transcripts,
authenticate producer claims, edit a running package, or publish automatically.

The optional Codex plugin `Stop` hook can request at most one continuation for
an original session/turn. It cannot guarantee one named-skill invocation:
matching hooks run concurrently, another hook may veto continuation, and model
routing is not deterministic. A persisted receipt remains available for the
portable explicit path. The receipt adapter never recursively invokes this or
another skill and never starts a repair loop.

## Canonical terminology

| Term | Contract |
|---|---|
| Receipt | Exact bounded producer outcome identified by its canonical digest. |
| Intake proposal | One durable local record per exact actionable receipt. |
| Analysis revision | One analyzer-version interpretation attached to that proposal. |
| Problem signature | Advisory v2 cluster from producer origin, signal, capability, invariant, and environment class. It cannot deduplicate, reopen, or authorize. |
| Evaluation manifest | Exact baseline, candidate, fixtures, environment, model, and rules for a comparison. |
| Evaluation result | Digest-bound per-fixture observations and a classification recomputed against one exact manifest. It is evidence input, not execution attestation. |
| Attempt / cycle receipt / termination receipt | Reserved for the later trusted-controller milestone; none is implemented by receipt intake. |
| Improvement | A predefined evaluation delta with no forbidden baseline regression, never protocol conformance alone. |
| Activation manifest | Exact release/package/install identity proved by a running skill; not implemented by this local loop. |
| Observed recurrence | Recurrence within measured receipt coverage; never a fleet-wide absence claim. |

## Receipt contract

Use `skill-outcome-receipt.schema.json`. Unknown fields fail closed. v2 adds a
closed `context` of capability ID, invariant ID, and enumerated environment
class to the v1 version/UUID, producer-declared package identity, outcome and
signal enums, timestamps, bounded causal depth, optional prior digest,
`action_performed: false`, and canonical digest. These fields remain
content-free.

`no_issue` must pair with `requested_action: none`; every other signal must
pair with `analyze_quality`. A no-action receipt writes only a bounded local
digest/provenance tombstone; it never requests a Stop continuation, creates a
proposal, or becomes contribution-eligible. Creation
time may be at most five minutes in the future and lifetime is at most 24
hours.

Problem signatures are explicitly advisory and their input authority is
`advisory_untrusted_intake`. v2 excludes version, package digest, timestamps,
receipt UUID, and project content from the signature. v1 lacks clustering
context, so every v1 receipt remains a singleton signature.

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
<python-3> scripts/skill_quality_loop.py --format json evaluation-validate --manifest <manifest.json> --result <result.json>
<python-3> scripts/skill_quality_loop.py --format json --state-dir <disposable-dir> conformance
```

With no marker, `consume` selects the oldest pending compatible receipt. Keep
state machine-local. Never sync receipts, proposals, or consents. Expired and
terminal receipt records and expired no-action tombstones are reclaimed.
Active proposals apply backpressure at the bounded limit; dismissing proposals
makes bounded capacity reusable.

`skill-quality-evaluation-manifest.schema.json`,
`skill-quality-evaluation-result.schema.json`, and
`scripts/_internal/skill_quality/attempt_contract.py` define the independent
comparison input and result. The manifest freezes receipt-count,
reproducibility, false-cluster, improvement, and regression thresholds. The
result must cover every frozen fixture exactly once and records only bounded
metrics, owner disposition/time, and unauthorized-outbound counts. Its summary
and classification are recomputed; observed failure dominates
`INCONCLUSIVE`. A valid artifact does not authenticate its author, prove that
an evaluation ran, or establish improvement beyond its exact evidence cell.

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

Inside that one owner-authorized candidate attempt, the protected workflow may
run at most three repair-and-recheck cycles. Each cycle rechecks the original
scope and changed surfaces. It stops cleanly when no material same-scope
finding remains, and stops without claiming convergence on a repeated finding
set, unchanged or previously seen candidate diff identity, oscillation,
forbidden scope, missing external evidence, an owner decision, or the third
cycle. This is bounded reanalysis inside one isolated agent invocation, not
receipt recursion. It never creates a follow-up issue or authorizes automatic
merge, release, publication, or installed update.

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
