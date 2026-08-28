# Skill Quality Learning Pilot Protocol

This directory scaffolds the manual, evaluation-first pilot. It does not claim
that a representative pilot, repair attempt, model evaluation, or improvement
has run.

## Purpose

Test whether content-free receipt families can support useful owner-authored
repairs before enabling any trusted repair controller. Receipt intake,
evaluation, owner authorization, publication, release, installed replacement,
activation, and observed recurrence remain separate lifecycle states.

## Frozen vocabulary

- Receipt: exact producer outcome identified by canonical digest.
- Intake proposal: one local record per exact actionable receipt.
- Analysis revision: analyzer-version interpretation attached to that proposal.
- Problem signature: advisory v2 cluster; never an authorization or effect key.
- Evaluation manifest: exact inputs and thresholds for a baseline/candidate run.
- Improvement: predefined evaluation lift with no forbidden baseline regression.
- Observed recurrence: recurrence only within the measured receipt denominator.

Attempt, cycle, termination, and activation receipts are not implemented by
this milestone.

## Selection and handling

1. Select 10 to 20 representative, content-free receipt signals across the
   frozen taxonomy. Every fixture must bind one distinct exact receipt digest
   plus capability, environment, invariant, producer-repository, and
   quality-signal dimensions. Persist only approved receipt fields and digests.
2. Freeze exact baseline/candidate package digests, fixtures, environment,
   dependency identity, model parameters, repetitions, and thresholds in one
   evaluation manifest before comparing outputs.
3. Have a human author each candidate repair. Do not invoke the protected
   autonomous repair workflow.
4. Replay the same frozen fixtures for baseline and candidate. If the model
   cell is not pinned, classify the comparison as `INCONCLUSIVE`.
5. Record results with the packaged closed evaluation-result schema. Validate
   the exact manifest/result pair with `skill_quality_loop.py
   evaluation-validate`; do not add free-form results to either artifact.
6. Stop without an improvement claim on missing evidence, baseline regression,
   ambiguous clustering, or incomplete denominator coverage.

## Pilot gates

The learning-value gate remains pending until persisted evidence supports all
of the following:

- 10 to 20 representative receipt signals;
- at least 80% baseline replay reproducibility;
- no more than 5% false problem clusters;
- owner time and disposition recorded for every selected signal;
- predefined evaluation lift with no forbidden baseline regression;
- zero unauthorized outbound actions or project-content capture.

Passing unit or conformance tests establishes protocol behavior only. The
synthetic manifest in this directory is deliberately unpinned and therefore
`INCONCLUSIVE`; it proves only closed-schema parsing.
