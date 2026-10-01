# Minimal local evidence nomination walkthrough

Run from the repository root with Python 3.10 or later, keeping the same terminal
for all steps. This example is synthetic: its accepted map is a test fixture,
not approval of a real project's evidence. The tiny UTF-8 corpus contains support,
counterevidence (intentional CRLF), and context.

`setup_project.py` creates a fresh copy with the current skill identity and a
matching request. It accepts only the bundled synthetic template, refuses an
existing destination, and leaves the checked-in project and frozen `golden/`
artifacts unchanged. It does not refresh real accepted maps. No JSON edits are
needed. Use a new destination when repeating setup after a skill update.

## First result: Windows PowerShell

```powershell
$demo = Join-Path $env:TEMP ("claims-demo-" + [guid]::NewGuid().ToString("N"))
py -3 -I examples/evidence-nomination/minimal/setup_project.py --output $demo
$project = "$demo/project"
$run = py -3 -I scripts/evidence_nomination.py nominate --request "$demo/request.json" --project-root $project --map-root "$project/map" --out-dir "$project/.analyze-project-claims/nominations" --format json | ConvertFrom-Json
py -3 -I scripts/evidence_nomination.py show --bundle $run.artifact_path
```

## First result: macOS / Linux

```sh
demo="$(mktemp -d)/walkthrough"
python3 -I examples/evidence-nomination/minimal/setup_project.py --output "$demo"
project="$demo/project"
python3 -I scripts/evidence_nomination.py nominate --request "$demo/request.json" --project-root "$project" --map-root "$project/map" --out-dir "$project/.analyze-project-claims/nominations" --format json
python3 -I scripts/evidence_nomination.py show --bundle "$project"/.analyze-project-claims/nominations/*.bundle.json
```

Expect three nominations: `context.txt`, `counter.txt`, and `support.txt`. The
content-derived filename starts with `nomination-`. The golden bundle, ready
selection and expected candidate in `golden/` are historical versioned examples;
their exact runtime identity is in `golden/identity.json`. The fresh synthetic
map's skill binding changes with the current release; Python Unicode versions
or code changes can also change bundle IDs. The semantic expected native payload
is [expected-observation.json](expected-observation.json).

## Explicit synthetic review and compilation

Read [review.json](review.json). It retains all three observations. For this
unchanged fixture only, `prepare_selection.py` binds that prerecorded review to
your runtime bundle. It allows only the exact historical request or the exact
current synthetic setup request; corpus, queries, nominations, exclusions,
truncations and completeness must still match the frozen example. It does not
infer a real project's review and refuses an existing output.

PowerShell:

```powershell
$bundle = $run.artifact_path
$directory = Split-Path $bundle
py -3 -I examples/evidence-nomination/minimal/prepare_selection.py --bundle $bundle --output "$directory/reviewed.selection.json"
py -3 -I scripts/evidence_nomination.py compile --bundle $bundle --selection "$directory/reviewed.selection.json" --project-root $project --map-root "$project/map" --output "$directory/component.candidate.json" --format json
py -3 -I scripts/evidence_nomination.py handoff --bundle $bundle --selection "$directory/reviewed.selection.json" --candidate "$directory/component.candidate.json" --project-root $project --map-root "$project/map" --output "$directory/native.payload.json" --format json
```

POSIX:

```sh
set -- "$project"/.analyze-project-claims/nominations/*.bundle.json
bundle="$1"
directory="$(dirname "$bundle")"
python3 -I examples/evidence-nomination/minimal/prepare_selection.py --bundle "$bundle" --output "$directory/reviewed.selection.json"
python3 -I scripts/evidence_nomination.py compile --bundle "$bundle" --selection "$directory/reviewed.selection.json" --project-root "$project" --map-root "$project/map" --output "$directory/component.candidate.json" --format json
python3 -I scripts/evidence_nomination.py handoff --bundle "$bundle" --selection "$directory/reviewed.selection.json" --candidate "$directory/component.candidate.json" --project-root "$project" --map-root "$project/map" --output "$directory/native.payload.json" --format json
```

Handoff prints a `next_command` argument array for the existing native reconciler.
Review it and invoke its script separately with ordinary `py -3` / `python3`,
preserving every expected identity argument. Do not shell-evaluate the JSON.
Reconciliation creates a proposed candidate; **do not run accept for this demo**.
After setup, these commands preserve the generated map and append no formal record.
The copied `record.json` remains historical fixture data; this component walkthrough
does not use it as a current claim record.

## Repeat and recover

Before preparing a review, repeating nominate reuses the identical bundle and
empty template. After review, run `verify` with the same bundle, project and map
arguments. Preserve sidecars; choose a fresh output directory after code/source
changes. A stale-source exit 4 means review must be repeated. A publication exit
5 may leave outputs and lists recovery artifacts. An incomplete review exits 2.

The commands above use a temporary directory. Keep nomination sidecars out of
version control when adapting them. For complete budgets, error codes, claim
handoffs, lifecycle, and client boundaries, read the
[packaged reference](../../../skills/analyze-project-claims/references/evidence-nomination.md).
