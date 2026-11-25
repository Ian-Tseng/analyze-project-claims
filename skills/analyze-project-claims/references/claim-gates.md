# Build gates from claims

A gate turns one claim into checks that can be run before anyone looks at the
results. Use gates when a claim will be judged repeatedly (after each run, in
CI, before a report) or when the success condition must be fixed in advance.
A quick audit of a claim with obvious evidence does not need one.

`scripts/claim_gates.py` uses only the Python standard library. It reads the
declared evidence files under one project root and never edits project records.

## 1. Start from atomic claims

Decompose compound statements first (see "Classify claims" in SKILL.md). For
each material claim, record:

- `claim_id` and `statement`, reusing the project's existing IDs;
- `role`: `execution_prerequisite`, `hypothesis` or `result`
  ([objective labels](objective-labels.md)). Only prerequisites can block other
  gates; a link alone does not make a claim a prerequisite;
- `coverage`: `direct` when the checks test the claim in its full stated scope,
  otherwise `partial`. Missing coverage defaults to `partial`;
- `depends_on`: claim IDs of prerequisites that must pass first;
- `criteria`: the machine-checkable checks, below.

The claims file can be a plain `{"claims": [...]}` file (see
`assets/claim-gates-claims.template.json`) or a v2 scan record. Scan-record
claims have no roles or criteria, so their gates start as `needs_criteria`.

## 2. Write checks that test the claim, not the paperwork

| Type | Passes when |
|---|---|
| `file_exists` | the file exists (use only for genuine prerequisites; existence is not validation) |
| `sha256` | the file's digest equals the recorded digest |
| `json_value` | the value at a JSON pointer satisfies `op value` |
| `json_compare` | value `op` (other value + `margin`), for example candidate >= baseline + 0.02 |
| `jsonl_count` | the number of non-empty lines satisfies `op value` |

Choose checks that would fail if the claim were false: a matched comparison,
an audit-passed field, the run manifest's own input digest. A runner marker or
artifact existence alone tests only that stage. Every check is required unless
`"required": false`.

## 3. Build, freeze, then evaluate

```powershell
py -3 scripts/claim_gates.py build    --claims claims.json --output gates.json
py -3 scripts/claim_gates.py validate --gates gates.json
py -3 scripts/claim_gates.py freeze   --gates gates.json
py -3 scripts/claim_gates.py evaluate --gates gates.json --project-root . --output gate-receipt.json
```

`freeze` records a digest of the gate definitions. `evaluate` refuses unfrozen
gates unless `--exploratory` is passed, and refuses gates edited after freezing.
To change a frozen gate, re-run `freeze --revision-reason "..."`; the old and new
digests and the reason are kept in `revisions`. Never weaken a threshold merely
to make a gate pass. In CI, add `--fail-on fail` or `--fail-on not-pass`.

## 4. Read the receipt

Each gate gets one outcome. A failed required check outweighs a missing one:

- **PASS:** every required check passed;
- **FAIL:** at least one required check failed;
- **INCONCLUSIVE:** no check failed, but evidence was missing, unreadable,
  non-numeric or outside the project root, or the gate has no criteria;
- **BLOCKED:** a prerequisite gate it depends on did not pass.

The receipt also records the digest of every evidence file it read, so a later
change to the evidence is visible.

Each gate's `claim_suggestion` maps the outcome onto claim statuses:

| Outcome | `direct` coverage | `partial` coverage |
|---|---|---|
| PASS | supported | partially_supported |
| FAIL | contradicted | review as counterevidence |
| INCONCLUSIVE or BLOCKED | keep current status or untested | same |

Suggestions always need review. Apply them only after checking the claim
classification, independence and completion rules in SKILL.md. Unfrozen
(exploratory) results stay exploratory. A PASS never establishes human
acceptance, independent replication, deployment readiness or a broader claim
than the gate tested. Record accepted changes in the existing project record
or scan record, not in a second claims ledger.
