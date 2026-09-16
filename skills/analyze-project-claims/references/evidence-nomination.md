# Local evidence nominations

Candidate version: 0.10.0. Publication and accepted-map release gates are
separate. This guide describes the source package; it does not claim that an
installed v0.9.0 includes these commands.

Given one explicitly identified claim or component gap, search approved local
roots and propose bounded excerpts. A nomination does not establish claim
status, authenticate a reviewer, accept a map, or append a formal record.

## Start with an explicit gap

Use the [v1 contract](evidence-nomination/v1/CONTRACT.md), the five closed schemas
beside it, and [request templates](../assets/evidence-nomination/). The requester
supplies the exact target, accepted-map identities, literal search terms, roles,
roots, and every resource-policy value. Claim targets also need a persisted v2
record and its exact identity. No terms, statuses, or budgets are inferred.

From the skill root, use `py -3 -I` on Windows or `python3 -I` on POSIX:

```text
py -3 -I scripts/evidence_nomination.py preflight --request <request.json> --project-root <project> --map-root <map-dir> --format json
py -3 -I scripts/evidence_nomination.py nominate --request <request.json> --project-root <project> --map-root <map-dir> --out-dir <project>/.analyze-project-claims/nominations --format json
py -3 -I scripts/evidence_nomination.py show --bundle <bundle.json> --format human
py -3 -I scripts/evidence_nomination.py verify --bundle <bundle.json> --project-root <project> --map-root <map-dir> --format json
```

Add `--record <persisted-v2-record.json>` to all scoped commands for a claim
target. A component request refuses that argument. Python 3.10 or later is
required. Use trusted local Python; isolated mode prevents project startup
imports. Run the repository's `examples/evidence-nomination/minimal/README.md`
walkthrough for a ready synthetic request with three known hits.

## Review and create a candidate

Nominate writes a bundle and an empty selection. Read the excerpts in their
source context, including counterevidence. Write the selection's nomination IDs,
formal evidence roles, summaries, rationales, and complete native reviewer input.
The informational reviewer label is not proof of authenticated human review.

```text
py -3 -I scripts/evidence_nomination.py compile --bundle <bundle.json> --selection <reviewed.json> --project-root <project> --map-root <map-dir> --output <candidate.json> --format json
py -3 -I scripts/evidence_nomination.py handoff --bundle <bundle.json> --selection <reviewed.json> --candidate <candidate.json> --project-root <project> --map-root <map-dir> --output <payload.json> --format json
```

Keep selection, candidate, and payload beside the bundle. Compilation validates
structure and provenance; handoff refreshes source/map/selection identity and
prints a native command array. Neither executes the native command.

| Target | Reviewer supplies | Separate next authority |
| --- | --- | --- |
| Claim | Full v2 input, exact inspected evidence items, IDs, role bindings, statuses and limitations | [v2 validate, review, then append](evidence-bound-audit-records.md) |
| Component | Full observation retaining all accepted component types, elements and targets | [reconcile, review, exact human acceptance, unchanged check](component-evidence-protocol.md) |

Invoke the printed native script with `py -3` or `python3`, preserving the array's
individual arguments. Native entrypoints use their documented ordinary Python
startup, not the nominator's isolated-mode startup. Never shell-evaluate the
array. Keep all three expected-map arguments and `--expected-input-sha256`.
Native guard failures exit 2; nomination freshness failures exit 4. Append needs
an explicitly selected log destination. Reconcile can leave candidate/delta
artifacts before a later guard failure; inspect them before retrying.

## Budgets and replay

The hard maxima are 2,500 files, 64 MiB total, 1 MiB per file, eight requirements,
5,000 matches, five nominations per requirement, 20 total nominations, 2 KiB
excerpts, 64 KiB selected ranges, and a ten-second checked deadline. See
[v1 policy](evidence-nomination/v1/policy.json). Count/byte truncation produces a
deterministic partial bundle. Timeout aborts without a bundle; blocking OS I/O
must return before Python can check elapsed time.

Replay binds source bytes, approved corpus, map/record, code, schemas, and Unicode
database. Different Python Unicode versions can intentionally produce different
bundle identities. Compare full bytes across operating systems with compatible
runtime identities. `show` checks self-integrity only; `verify` checks freshness.
New/deleted files in the scanned corpus can invalidate replay. Keep sidecars in
the original excluded output directory.

## Artifact lifecycle and recovery

Sidecars may contain private excerpts. Keep the conventional output directory
ignored by Git. Outputs must remain inside the project, outside the accepted map,
formal validation directory, and skill installations. Review before sharing.

| Exit / outcome | Effect | Next action |
| --- | --- | --- |
| 0 complete / partial / zero | Bundle and empty selection, possibly truncated | Review scope; zero is an unresolved gap, not a pass |
| 0 reused_identical | Identical artifacts retained | Show or verify; no review overwritten |
| 2 invalid / unsafe / incomplete | Refusal | Correct explicit inputs or reviewer fields |
| 3 I/O / timeout | Retryable failure | Narrow roots or fix local I/O; rerun |
| 4 stale / tampered | Identity mismatch | Nominate again and review the new bundle |
| 5 publication / recovery | Some files can survive | Inspect reported artifacts; choose a new output directory |

Exclusive publication never overwrites different bytes. After editing a selection,
use verify rather than repeating nominate into its directory. Bundle/selection
publication is not a multi-file transaction. Preserve reviewed and failed-run
artifacts when diagnosing a failure.

Reads reject path traversal, links/reparse points, hard-linked source aliases,
Windows device/ADS names, case collisions, unsafe controls, and configured secret
patterns. Binary, archives, LFS pointers, and oversize inputs are excluded with
content-free diagnostics. Secret patterns cannot recognize every possible secret.
Filesystem race checks have tested scope; they do not lock an entire corpus or
establish safety against every continuously hostile same-user/privileged writer.

## Codex and Claude boundary

An operator may explicitly ask either client to prepare a request or explain a
receipt. Require the gap, terms and roots before running. Ask the reviewer to
supply evidence roles, statuses and acceptance decisions. No hook auto-runs
nomination, no search loads project code or invokes another skill, and no receipt
proves client discovery or invocation. External search and related-skill discovery
remain deferred pending the separate frozen usefulness pilot.
