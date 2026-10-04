# Agent-pool evaluation protocol

This directory supplies behavioral regressions and a finite benchmark of the real Python controller and subprocess workers. The reviewer adapter is deterministic fixture code, not an LLM or a real invocation of the claims skill. Its `skill_invocation` field is a fixture attestation needed to exercise the transport schema.

## Run

Run from the repository root using Python 3.10 or later:

```text
python -m unittest discover -s tests -p test_agent_pool.py
python evaluation/agent-pool/benchmark.py --output /new/external/run-directory --workers 2 --iterations 2000000 --repeats 3 --timeout 180
```

Use a new output directory outside the publishable checkout: journals contain local paths, host process IDs and raw observations. Output directories are never overwritten. The Windows equivalent is `py -3`. Preserve failed, interrupted and inconclusive attempts beside successful attempts.

Freeze the implementation and benchmark before a timing run. Stop competing test/benchmark jobs first; do not stop unrelated user work. Record other known machine load as a limitation. Source hashes are recorded before trials and checked at trial end and summary. A change invalidates the attempt.

## Fixed workload and comparison

The DAG is `a -> d -> f`, `b -> e -> f`, and `c -> f`. Task a has four times the PBKDF2 iteration count of each other task. Each task reads the fixed protocol plus its actual predecessor output digests, computes PBKDF2-HMAC-SHA256, and atomically writes JSON. Expected outputs are computed and frozen before timing. There is no sleep-based simulated workload; the coordinator uses a short polling backoff while real processes run.

Output claims mean exact equality to this frozen protocol. They share the protocol prerequisite, but do not assert a global scientific conclusion. Task dependencies and `required_claims` enforce reviewed predecessor outcomes. Every completed unit is reviewed, and final completion requires the entire DAG. The pool additionally performs its required final global review.

Baseline and candidate use the same candidate controller source, DAG, task iteration counts, output checks, deterministic reviewer, resource ceiling and process startup boundary. Baseline omits `agent_pool`; candidate enables the explicit pool. Both start the same number of persistent worker processes plus a separate reviewer. Actual process IDs are bound to assignments and reused with recorded idle observations. This is local subprocess adapter evidence, not native Codex thread lifecycle evidence.

Trial order alternates serialized/pool then pool/serialized. Timing begins after controller initialization and includes host startup, controller operations, work, reviews and result integration through reported completion. Expected-value generation, initialization, result inspection and host shutdown are excluded consistently. Host responses and the trial have finite deadlines; only owned helpers are cleaned up.

## Acceptance and measurement

For every trial verify exact output equality, one execution per task, clean reviewed claims and completed controller state. Save each worker's wall and CPU durations, raw dispatch/result/reviewer events, wall time inside controller calls and dependency-review-to-dispatch delays. Controller-call time overlaps live subprocess work and is not additive exclusive overhead. These delays include scheduler/resource waits; they are not all avoidable idle time.

Prove overlap using actual worker execution intervals. Prove refill using a reused worker's new assignment after a has actually started and before a finishes; a's own dispatch cannot satisfy this test. Acceleration evidence is inconclusive unless output checks pass and every pool trial exhibits both overlap and refill. Preserve individual paired ratios and the median; a median above one is descriptive evidence for this workload, not a statistical significance result or a general performance guarantee.

The 1,000-iteration functional smoke is too small for a speed claim and is kept separately. A different workload size may be evaluated only as an explicitly recorded new experiment; do not delete slower or inconclusive runs or silently retune the original manifest.

`fail-first.json` records the initial regression outcome; its raw log is retained outside the publishable checkout. Full measured reports belong to their exact frozen run artifacts and source hashes.
