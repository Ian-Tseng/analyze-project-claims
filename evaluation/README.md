
# Cross-project reliability evaluation kit

This directory turns the paper-facing evaluation plan into an executable,
claim-bounded lifecycle. It compares `agent_only`, `generic_checklist`, and
`skill_assisted` conditions over a complete project x condition x agent-family x repeat grid.

The bundled run uses two synthetic projects and two scripted output families.
It is a workflow dry run, not a reliability experiment. Its scores only test
metric arithmetic and failure paths.

## Claim-expansion plan

A broader reliability claim requires a frozen, independently labelled
evaluation. The planned progression is:

1. sample multiple natural research or engineering project packages;
2. define blinded element-level inconsistency labels before agent runs;
3. compare agent-only, generic-checklist, and skill-assisted conditions;
4. measure detection precision and recall, false-positive rate, repair
   correctness, provenance preservation, elapsed time, and token cost;
5. repeat across at least two version-frozen agent or model families;
6. ablate typed lifecycle states, authority ordering, provenance checks,
   formal operators, and hierarchical scan records;
7. retain negative results and predeclare expansion or stop conditions.

Until that work is complete, describe this project as a reusable auditing
workflow with deterministic structure reconciliation and logging, not as a
generally reliable auditor.

## Run the dry-run preflight

From the public repository root:

```powershell
py evaluation/scripts/cross_project_reliability.py preflight `
  --config evaluation/configs/dry-run.json
```

Run the complete fixture lifecycle:

```powershell
py evaluation/scripts/cross_project_reliability.py dry-run `
  --config evaluation/configs/dry-run.json `
  --output-root runs/analyze_project_claims_reliability
```

The command creates a frozen scientific identity, blinded project packets,
one required spec for every grid cell, submissions and separate adjudications,
per-spec completion markers, project-unit metrics, a runner marker, a replay
audit, and final lifecycle completion evidence. Gold labels and the fixture
plan never enter `packets/`.

## Calibrate the human codebook before study labels

Use the separate one-project practice selection before either annotator opens a
frozen development-pilot packet. The calibration repository and every practice
artifact are permanently excluded from development, confirmation, manuscript
tables, and reliability claims.

```powershell
py evaluation/scripts/annotation_calibration.py preflight `
  --selection evaluation/configs/annotation-calibration.selection.json

py evaluation/scripts/annotation_calibration.py prepare `
  --selection evaluation/configs/annotation-calibration.selection.json `
  --snapshot-root <non-public-calibration-snapshot-root> `
  --output-root <non-public-calibration-run-root> `
  --codebook evaluation/annotation-codebook.md
```

The command validates the exact commit, archive and license hashes, copies two
independent human practice packets, binds the initial codebook SHA-256, and
creates a blank discussion record. It creates no human labels and no
agent-execution gate. Each human completes a first pass without seeing the
other pass. Validate exactly two completed, distinct human records before
discussion:

```powershell
py evaluation/scripts/annotation_calibration.py label-preflight `
  --run-dir <prepared-calibration-run>
```

Record disagreements and codebook decisions in
`review/calibration_discussion.json`. Then freeze the completed calibration and
the exact final codebook bytes:

```powershell
py evaluation/scripts/annotation_calibration.py freeze `
  --run-dir <prepared-calibration-run> `
  --final-codebook <final-codebook.md>

py evaluation/scripts/annotation_calibration.py status `
  --run-dir <prepared-calibration-run>
```

The freeze writes a hash-bound training-only calibration commitment. It does
not make the practice project paper-table evidence and never authorizes agent
execution.

### Use the local Calibration Console

The dependency-free UI covers source review, structured element and finding
forms, private browser drafts, immutable final submission, post-hash discussion,
final-codebook freeze, and optional study binding. Launch it from the public
repository root with the prepared non-public run directories:

```powershell
py evaluation/scripts/calibration_ui.py `
  --run-dir <prepared-calibration-run> `
  --pilot-run-dir <prepared-natural-pilot-run>
```

The server binds only to loopback and prints one coordinator URL plus one
unguessable URL for each annotator slot. Give each human only their assigned
annotator URL. The coordinator can see submission state but cannot read either
record until both independent files pass preflight. Closing the UI does not
alter committed artifacts; restarting it creates fresh access tokens over the
same validated run state. Use `--no-browser` when distributing the printed URLs
manually.

## Freeze the natural-project pilot before labels

The development pilot has a separate selection and annotation gate. First,
validate the metadata-only sample without inspecting project outcomes:

```powershell
py evaluation/scripts/natural_project_pilot.py preflight \`
  --selection evaluation/configs/natural-development-pilot.selection.json
```

Acquire each exact commit outside this public repository, preserve its license,
and add a `.apc-source.json` provenance record matching
`schemas/pinned-project-source.schema.json`. Then prepare two condition-blinded
annotation packet sets:

```powershell
py evaluation/scripts/natural_project_pilot.py prepare-annotations \`
  --selection evaluation/configs/natural-development-pilot.selection.json \`
  --snapshot-root <non-public-snapshot-root> \`
  --output-root <non-public-run-root>
```

The command refuses natural snapshots inside the public bundle, validates
commit-bound acquisition and license hashes, enforces frozen file/byte caps,
and creates one packet per project and annotator slot. It deliberately leaves
agent execution blocked. Check that boundary with:

```powershell
py evaluation/scripts/natural_project_pilot.py gate --run-dir <prepared-run>
```

Before any development labels are written, bind the completed calibration and
its frozen final codebook into the prepared study:

```powershell
py evaluation/scripts/natural_project_pilot.py bind-codebook `
  --run-dir <prepared-run> `
  --calibration-run-dir <completed-calibration-run>
```

The binding copies the calibration commitment and final codebook into the
study, records their hashes, excludes the practice evidence from study
outcomes, and fails closed if calibration is incomplete or later bytes change.

Follow the bound `protocol/frozen-annotation-codebook.md`. Save exactly one
completed annotation for each project-slot cell under `review/raw_labels/`,
then validate the eight raw artifacts and obtain the exact hashes needed by the
blinded adjudicator:

```powershell
py evaluation/scripts/natural_project_pilot.py label-preflight `
  --run-dir <prepared-run>
```

After a third independent human has written one condition-blinded gold file
per project under `review/gold/`, freeze the label set:

```powershell
py evaluation/scripts/natural_project_pilot.py freeze-labels `
  --run-dir <prepared-run>
```

The controller recomputes exact project-slot coverage, identities, selection
and snapshot bindings, attestations, source-finding references, and every
raw/gold hash before atomically writing `review/label_commitment.json`. The
execution gate revalidates those bytes and fails closed after tampering; it
does not trust a hand-written summary commitment.

A ready execution gate requires a valid frozen calibration-to-study codebook
binding, two completed independent human-label sets, condition-blinded
adjudicated gold from the third human, and exact versions for at least two live
agent/model families. Label freezing is not a reliability result. Third-party source snapshots and human review files must not be
committed to this public package.

## Move beyond the fixture

Use `configs/development-pilot.template.json` for a 4-6 natural-project pilot.
Replace every placeholder and use live, version-frozen agent/model families.
Obtain two independent human labels per project and adjudicate without knowing
the condition. The originating RAG project and the synthetic fixtures cannot
be confirmatory projects.

Use pilot project-level variance to complete and preregister
`configs/confirmatory.template.json`. A confirmatory run must use unseen
projects and at least two non-scripted agent/model families. Do not treat
repeats, findings, or elements as independent project replications.

See `protocol.md` for metrics, gates, and the claim boundary. Exchange formats
are documented in `schemas/` and are also enforced by the standard-library
harness.


