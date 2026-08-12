
# Cross-project reliability protocol

## Objective and estimand

Estimate whether using `analyze-project-claims` changes inconsistency
detection, repair quality, provenance preservation, time, and token cost across
the sampled projects and frozen agent/model families, relative to agent-only
and generic-checklist controls.

The primary independent unit is the project. Project-condition-family-repeat
cells are paired observations; individual findings and elements are not
independent replications.

## Frozen conditions

| Condition | Supplied guidance |
|---|---|
| `agent_only` | Audit task and output contract only |
| `generic_checklist` | Non-specialized consistency checklist |
| `skill_assisted` | Same task plus the installed skill workflow |

Project packets must be byte-identical across conditions. Conditions may
differ only in their declared prompt/skill access. Gold labels, adjudications,
prior agent outputs, and project outcomes are excluded from every packet.

## Labels and review

Natural-project selection is frozen from repository metadata, exact commit,
language/task stratum, and license evidence before inconsistency outcomes are
inspected. The development sample may be purposive, but its non-probability
status must be explicit. Third-party snapshots remain outside the public kit.

Before study labeling, two humans calibrate the codebook on one separately
identified natural repository. They complete independent first passes before
discussion. The resulting discussion, exact raw-label hashes, distinct
annotator identities, and final codebook bytes are frozen into a calibration
commitment. A development study must copy and hash-bind that commitment and
codebook before accepting any study labels. The practice repository, labels,
disagreements, and revision decisions are training-only artifacts and are
prohibited from development, confirmation, paper-table, and reliability
evidence. Calibration does not require or authorize agent execution.

Natural-project evaluations require at least two independent human annotators.
Annotators label the element inventory and gold findings before agent results
are reviewed. Result adjudicators map submitted findings to gold IDs or to
`null`, assess repair correctness and provenance preservation, and remain
blinded to condition. Disagreements are retained and resolved under a frozen
rule; raw labels are never overwritten.

## Metrics

Finding precision, recall, and F1 use one-to-one adjudicated finding-to-gold
matches. Element precision, recall, and F1 use the predeclared element
inventory. Severe-finding recall uses gold severity. False-positive element
rate is the number of non-gold elements receiving at least one unmatched
finding divided by all predeclared non-gold elements. Repair correctness and
provenance preservation are proportions over applicable matched repairs. Time,
input tokens, and output tokens come from each frozen agent run.
A project may have zero adjudicated gold findings. In that case, undefined
precision, recall, F1, severe-recall, and matched-condition deltas are stored as
`null` and excluded from their macro mean; they are never replaced with a
perfect score. A submitted false positive still yields zero finding precision
and F1, and every zero-gold project remains evaluable through false-positive
element rate.

Report project-unit macro means and paired condition deltas. A natural-project
pilot estimates project-level variance; confirmatory uncertainty and power use
projects as clusters. Do not substitute question-, element-, finding-, seed-,
or repeat-level resampling for project-level uncertainty.

## Lifecycle gates

Pre-execution readiness requires a frozen selection, validated source and
license hashes, two byte-identical condition-blinded annotation packet sets, a
valid frozen calibration-to-study codebook binding, two completed independent
human labels per project, frozen blinded gold, and at least two exact live
agent/model-family versions. Selection or packet
preparation alone keeps `scientific_state=untested` and agent execution blocked.

Accepted lifecycle completion requires every declared grid cell, a readable
submission and adjudication, matching scientific hash, a valid per-spec
marker, the runner marker, a passing replay audit, and the audit-completion
marker. The replay shares the collector implementation and is not an
independent implementation or scientific replication.

Scientific support and paper eligibility are separate. The bundled dry run is
always `scientific_state=untested`, `acceptance_state=not_eligible`,
`paper_table_eligible=false`, and `general_reliability_proved=false`.

## Stage gates

| Stage | Minimum evidence | Maximum claim |
|---|---|---|
| Workflow dry run | Two synthetic packets; complete scripted grid; lifecycle/audit pass | Evaluation machinery behaves on fixtures |
| Human codebook calibration | One separate natural practice project; two independent first passes; recorded disagreement discussion | Codebook usability and annotator training only; no study evidence |
| Development pilot | 4-6 natural projects; two live families; independent blinded labels | Protocol feasibility and variance estimate in evaluated pilot |
| Confirmatory | Powered preregistered unseen projects; two or more live families; frozen labels and analysis | Bounded effect across the evaluated projects, strata, families, and versions |

No finite study proves universal reliability across every project, agent,
model, domain, or task.


