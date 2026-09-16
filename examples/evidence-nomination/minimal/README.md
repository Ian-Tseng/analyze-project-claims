# Minimal local evidence nomination walkthrough

Run from the repository root with Python 3.10 or later. This example is synthetic:
its accepted map is a test fixture, not approval of a real project's evidence.
The tiny UTF-8 corpus contains support, counterevidence (intentional CRLF), and
context. No JSON edits are needed before the first result. The candidate source
is unreleased; installed v0.9.0 does not contain this command.

## First result: Windows PowerShell

```powershell
$run = py -3 -I scripts/evidence_nomination.py nominate --request examples/evidence-nomination/minimal/request.json --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --out-dir examples/evidence-nomination/minimal/project/.analyze-project-claims/nominations --format json | ConvertFrom-Json
py -3 -I scripts/evidence_nomination.py show --bundle $run.artifact_path
```

## First result: macOS / Linux

```sh
python3 -I scripts/evidence_nomination.py nominate --request examples/evidence-nomination/minimal/request.json --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --out-dir examples/evidence-nomination/minimal/project/.analyze-project-claims/nominations --format json
python3 -I scripts/evidence_nomination.py show --bundle examples/evidence-nomination/minimal/project/.analyze-project-claims/nominations/*.bundle.json
```

Expect three nominations: `context.txt`, `counter.txt`, and `support.txt`. The
content-derived filename starts with `nomination-`. The golden bundle, ready
selection and expected candidate in `golden/` are versioned examples; their exact
runtime identity is in `golden/identity.json`. Python Unicode versions or code
changes can change their IDs. The semantic expected native payload is
[expected-observation.json](expected-observation.json).

## Explicit synthetic review and compilation

Read [review.json](review.json). It retains all three observations. For this
unchanged fixture only, `prepare_selection.py` binds that prerecorded review to
your runtime bundle. It does not infer a real project's review. It refuses a
different request/corpus/nomination set and refuses an existing output.

PowerShell:

```powershell
$bundle = $run.artifact_path
$directory = Split-Path $bundle
py -3 -I examples/evidence-nomination/minimal/prepare_selection.py --bundle $bundle --output "$directory/reviewed.selection.json"
py -3 -I scripts/evidence_nomination.py compile --bundle $bundle --selection "$directory/reviewed.selection.json" --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --output "$directory/component.candidate.json" --format json
py -3 -I scripts/evidence_nomination.py handoff --bundle $bundle --selection "$directory/reviewed.selection.json" --candidate "$directory/component.candidate.json" --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --output "$directory/native.payload.json" --format json
```

POSIX:

```sh
set -- examples/evidence-nomination/minimal/project/.analyze-project-claims/nominations/*.bundle.json
bundle="$1"
directory="$(dirname "$bundle")"
python3 -I examples/evidence-nomination/minimal/prepare_selection.py --bundle "$bundle" --output "$directory/reviewed.selection.json"
python3 -I scripts/evidence_nomination.py compile --bundle "$bundle" --selection "$directory/reviewed.selection.json" --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --output "$directory/component.candidate.json" --format json
python3 -I scripts/evidence_nomination.py handoff --bundle "$bundle" --selection "$directory/reviewed.selection.json" --candidate "$directory/component.candidate.json" --project-root examples/evidence-nomination/minimal/project --map-root examples/evidence-nomination/minimal/project/map --output "$directory/native.payload.json" --format json
```

Handoff prints a `next_command` argument array for the existing native reconciler.
Review it and invoke its script separately with ordinary `py -3` / `python3`,
preserving every expected identity argument. Do not shell-evaluate the JSON.
Reconciliation creates a proposed candidate; **do not run accept for this demo**.
No command above changes the accepted map or appends a formal record.

## Repeat and recover

Before preparing a review, repeating nominate reuses the identical bundle and
empty template. After review, run `verify` with the same bundle, project and map
arguments. Preserve sidecars; choose a fresh output directory after code/source
changes. A stale-source exit 4 means review must be repeated. A publication exit
5 may leave outputs and lists recovery artifacts. An incomplete review exits 2.

Keep `.analyze-project-claims/nominations/` ignored. For complete budgets, error
codes, claim handoffs, lifecycle, and client boundaries, read the
[packaged reference](../../../skills/analyze-project-claims/references/evidence-nomination.md).
