# Evidence nomination development pilot

Protocol draft: nomination-pilot-v1. Status: **not frozen; no pilot executed**.
This is the T7 local-finder study, separate from the whole-audit natural-project
pilot and the skill-quality-loop pilot. Do not reuse their results as finder data.

## Freeze before nomination

1. Select 20 naturally occurring unresolved evidence gaps from at least four
   repositories: ten persisted-claim targets and ten component-element targets.
   Pin each repository commit and raw snapshot manifest, the accepted map's three
   identities, exact claim record when applicable, request JSON, approved roots,
   query terms and budgets. Each gap must come from an existing audit/reconciler
   finding, not be invented to match the finder output.
2. Include independently labeled counterevidence and insufficient/zero-result
   cases. A reviewer who has not seen nomination output labels useful spans,
   support validity and counterevidence spans against the exact frozen target.
   A separate reviewer adjudicates disagreements before outputs are exposed.
3. Freeze the label file, request set, software/code/schema/Unicode identity,
   this protocol, reviewers, paired task assignments and order allocation by
   SHA-256. Record who saw which labels/output and when. Candidate selection
   becomes immutable only after these fields are complete and the freeze is
   explicitly recorded; the empty template below is not a frozen study.
4. Use separate matched reviewers for the manual and assisted conditions per
   gap, counterbalancing reviewer/condition assignment across gaps to limit
   carryover. Pair by gap. Record manual search tools and the same corpus access
   for both conditions. If only one reviewer is available, revise and freeze a
   crossover protocol with an explicit carryover limitation before running.

## Collect actual observations

Start the timer when the reviewer receives the gap and frozen corpus. Stop when
that reviewer submits a reviewed selection and candidate or records the evidence
as insufficient. Include request preparation, result inspection, counterevidence
review, selection editing and validation in assisted time. Record start/stop
observations and elapsed seconds; CLI duration is not human reviewer time.

For each condition retain the request, selected locators and roles, candidate,
native-validation receipt, complete command log and actual timing evidence.
Retain all nomination bundles, including failures, timeouts and zero results.
Do not tune terms or rerun only failed cases after seeing labels. Corrections
require a new identified study attempt with the original attempts preserved.

## Compute the prespecified gates

Rank the distinct nominations by the bundle's frozen order and use the first
five per gap (across requirements). Compare exact source/byte spans with the
independently adjudicated gold; any overlap rule must be frozen in the label
codebook before use.

| Gate | Definition | Advance threshold |
| --- | --- | --- |
| Precision at five | Mean over all 20 gaps of useful top-five hits / 5; unfilled positions count as zero | >= 0.70 |
| False-support rate | Top-five nominations requested as support but not independently labeled valid support / all top-five support nominations | <= 0.05 |
| Missed counterevidence | Gold counterevidence spans absent from the corresponding gap's top five / all gold counterevidence spans | <= 0.10 |
| Paired review time | Median of `(manual_seconds - assisted_seconds) / manual_seconds` over the 20 paired gaps | >= 0.30 |
| Candidate conversion | Assisted gaps with a submitted reviewed selection and native-valid candidate / 20 frozen gaps, including failed/zero cases | >= 0.80 |
| Replay | Exact artifact hashes agree across Windows, Linux and macOS within the same source/schema/Unicode identity | All compared artifacts identical |
| Side effects | Observed network calls, child processes, project imports, accepted-state changes and installation changes during finder execution | All zero |

If there are no support nominations or no labeled counterevidence, the relevant
rate is undefined and the study is INCONCLUSIVE, not PASS. Missing timings,
labels, required identities, platform cells, or side-effect observations also
make the complete gate INCONCLUSIVE. Report any measured failures separately;
a known failure still prevents advancement when another metric is missing.

Report all numerators, denominators, per-gap rows, paired times, failures, source
identities, label exposure, and protocol deviations. Do not substitute a synthetic
run, self-authored labels or model-generated times for independent human evidence.
Passing these gates supports only this frozen development sample, not broad
reliability or scientific improvement. External and related-skill search stay
deferred unless every gate passes.

## Working files and resumption

Copy [study.template.json](study.template.json) into a private evaluation workspace
and fill its 20 rows using genuine audit gaps and independently prepared labels.
Keep source snapshots, annotations, timings and private excerpts outside Git.
The immediate missing inputs are the four repository snapshots, their valid maps
(and claim records), 20 adjudicated gaps, and participating human reviewers.
The implementation and documentation work can proceed while those are prepared.
