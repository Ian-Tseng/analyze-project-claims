# Natural-project annotation and adjudication codebook

This codebook governs the development pilot's independent human labels and
condition-blinded adjudicated gold. It does not authorize agent execution,
scientific acceptance, paper-table eligibility, or a general-reliability
claim.

## Non-study calibration exercise

Before labeling the frozen development projects, two humans should complete
one separate natural-project practice exercise with
`evaluation/scripts/annotation_calibration.py`. They first annotate
independently, hash their completed practice files, and only then discuss
disagreements and any codebook revision. The practice repository, labels,
discussion, and derived decisions are training material only: never reuse them
as development or confirmation data, never include them in a paper table, and
never count them as evidence of reliability. A revised codebook starts a new
hash-bound study label set; it does not change already frozen evidence.

## Roles and blindness

- Assign two different humans to the frozen annotator slots. Each person uses
  one stable opaque `annotator_id` across all projects.
- Annotators work independently. They must not see the other annotator's
  labels, agent prompts, condition names, agent outputs, or gold labels.
- A third human adjudicator reviews the two completed label sets while still
  blind to agent conditions and outputs. The adjudicator must not be either
  annotator.
- Do not pre-fill attestations as true. Each human changes the relevant fields
  to `true` only after personally satisfying them and records `attested_at`.

Raw labels, adjudication files, identity material, and natural-project source
snapshots stay outside the public package.

## Unit of annotation

Inventory the project from components down to concrete elements. Reuse an
existing accepted component-to-element map when it covers the frozen snapshot;
otherwise build a provisional inventory for annotation. A component is a
coherent project subsystem. An element is one directly inspectable artifact,
claim, configuration, schema, implementation, test, table, or lifecycle
marker.

Every project requires a non-empty `element_inventory`, even when no
inconsistency is found. For each element record:

- a stable `element_id` and its parent `component_id`;
- a snapshot-relative `path` and an `element_type`;
- exactly one evidence method in `observed_state`: `inspected`,
  `schema_validated`, `executed_test`, `replayed`, `inferred`, or
  `not_tested`.

Do not mark an element `executed_test` merely because a test file exists or was
read. Missing evidence is unknown, not false.

## Candidate findings

Create a candidate finding only when at least two inventoried elements expose
a same-scope inconsistency. Classify it as `definition`, `type_or_flow`,
`scope`, `claim_evidence`, `goal_metric`, `lifecycle`, `monitor`, `document`,
or `provenance`.

Each finding records:

1. the primary and conflicting element IDs;
2. why the elements conflict;
3. direct evidence and separately preserved counterevidence;
4. the safest current interpretation;
5. the repair or evidence needed to resolve it;
6. claim status: `partially_supported`, `contradicted`, `untested`, or
   `invalidly_specified`;
7. severity: `low`, `moderate`, or `severe`.

`Contradicted` is not predefined merely because two strings differ. It requires
same-scope counterevidence that directly conflicts with the claim. `Untested`
means no direct test exists. `Invalidly_specified` means the population,
protocol, metric, comparator, or state definition is incomplete.

A completed annotation may contain zero `candidate_findings`. Never invent a
finding to satisfy a quota.

## Operator definition

When an annotation actually concerns the finite-state operators, use the
project's declared domain rather than ordinary-language negation. For a finite
domain \(D\):

\[
\neg A = D \setminus A, \qquad
A \land B = A \cap B, \qquad
A \lor B = A \cup B.
\]

For a current singleton state \(s\),
\(\operatorname{NOT}(s)=D\setminus\{s\}\). In the three-state domain
\(\{\mathrm{SUPPORT},\mathrm{CONTRADICT},\mathrm{NOINFO}\}\), this is an
exact two-candidate complement over the three-state label domain. Candidate
enumeration is not transition authorization or execution.

## File workflow

1. Each annotator copies their packet's `annotation.template.json`, completes
   it, and saves it as:

   ```text
   review/raw_labels/<annotator_slot_id>/<project_id>.json
   ```

2. After all project-slot cells are complete, validate coverage and obtain the
   exact source hashes for adjudication:

   ```powershell
   py evaluation/scripts/natural_project_pilot.py label-preflight `
     --run-dir <prepared-run>
   ```

3. The adjudicator creates one
   `APC_BLINDED_ADJUDICATED_GOLD_V1` object per project at
   `review/gold/<project_id>.json`. Copy the exact per-slot hashes from
   `adjudication_inputs[].source_annotation_sha256`. Preserve disagreements;
   do not force a positive finding. Each gold finding must reference at least
   one valid source candidate ID.
   A zero-finding gold set is valid. The evaluation protocol stores undefined
   detection metrics and paired deltas as `null`, excludes them from macro
   means, and still scores false-positive element rate; it never substitutes a
   perfect detection score.

4. Freeze the complete label set:

   ```powershell
   py evaluation/scripts/natural_project_pilot.py freeze-labels `
     --run-dir <prepared-run>
   ```

The freeze command validates exact project-slot coverage, stable and distinct
human identities, selection and snapshot identity, source finding references,
attestations, and every raw/gold SHA-256. It then atomically writes
`review/label_commitment.json`. Re-running is idempotent only while every bound
byte remains unchanged.

5. Check the remaining execution gates:

   ```powershell
   py evaluation/scripts/natural_project_pilot.py gate --run-dir <prepared-run>
   ```

After label freezing, `two_live_agent_families` should remain the only missing
gate. If any bound artifact changes, the gate fails closed with
`invalid_label_commitment`; start a new explicitly identified label set rather
than editing the frozen commitment.
