# SkillOutcomeReceipt v1

`SkillOutcomeReceipt` is a small, content-free handoff from a compatible
Ian-Tseng-managed skill to `analyze-project-claims`. It is a signal to create a
local review proposal. It is not a finding, patch, instruction, authorization,
or proof that an update occurred.

The executable contract is
`skills/analyze-project-claims/references/skill-outcome-receipt.schema.json`.
The validator and canonical digest implementation live in
`skills/analyze-project-claims/scripts/_internal/skill_quality/contract.py`.

## Closed fields

The v1 receipt contains only:

- schema version and random receipt UUID;
- producer-declared owner, repository, skill, SemVer, and package SHA-256;
- enumerated outcome, quality signal, and requested action;
- `action_performed: false`;
- creation and expiry timestamps;
- causal depth zero or one and an optional prior digest;
- canonical receipt SHA-256.

Producer identity is explicitly `producer_declared_untrusted`. A receipt does
not authenticate its producer. Owner contribution still requires exact
destination, authenticated GitHub identity, owner-applied label, protected
workflow, patch guard, tests, human review, release, and installed activation.

Unknown fields and inconsistent signal/action pairs fail closed. `no_issue`
requires `requested_action: none`; every other signal requires
`analyze_quality`. Receipts more than five minutes in the future are
rejected. Receipts must not contain free text, prompts,
transcripts, paths, URLs, logs, tool input or output, project findings, stack
traces, diffs, patches, tokens, credentials, or attachments. The canonical JSON
is capped at 3 KiB and its single-line marker at 4 KiB. Lifetime is at most 24
hours and causal depth is at most one.

## Producer integration

After finishing the producer's substantive result, use the installed analyzer
helper to create a marker:

```powershell
py -3 <analyzer-skill-root>\scripts\skill_quality_loop.py --format json emit `
  --repository <producer-repository> `
  --skill <producer-skill> `
  --version <producer-version> `
  --package-digest <64-lowercase-hex> `
  --outcome completed_with_limitations `
  --quality-signal claim_evidence_gap
```

On POSIX hosts, use `python3` and `/` separators. Append only the returned
`marker` as the final line of the producer result. Do not add project content to
the marker.

Each producer must select one signal:

| Signal | Local recommendation |
|---|---|
| `claim_evidence_gap` | Review claim-to-evidence binding |
| `lifecycle_inconsistency` | Review lifecycle state contracts |
| `documentation_mismatch` | Review active documentation contracts |
| `internal_failure` | Prepare a bounded regression |
| `no_issue` | No change recommended |

Use `requested_action: none` and `no_issue` when there is no quality follow-up.
The Stop adapter ignores that pair and explicit consumption returns
`NO_QUALITY_FOLLOWUP` without a proposal. Do not emit a receipt merely to
force an analyzer invocation.

## Portable consumer path

On a host without the trusted Codex plugin adapter, explicitly invoke the
analyzer with the marker:

```text
/analyze-project-claims consume this exact SkillOutcomeReceipt marker and create
one local proposal; do not submit, edit, release, or update anything:
SKILL_OUTCOME_RECEIPT_V1:<token>
```

The skill calls:

```powershell
py -3 <skill-root>\scripts\skill_quality_loop.py --format json consume `
  --marker SKILL_OUTCOME_RECEIPT_V1:<token>
```

Replay returns the same proposal ID. The unique effect key is the receipt
digest plus analyzer version.

## Producer conformance

The repository contains two unrelated enum-only examples under
`examples/quality-loop-producers/`. Run the offline product fixture with:

```powershell
py -3 skills\analyze-project-claims\scripts\skill_quality_loop.py `
  --format json --state-dir <disposable-directory> conformance
```

Success is `QUALITY_PROPOSAL_READY`, `replay_deduplicated: true`, and
`outbound: NONE`. This proves only the local fixture and tested contract.
