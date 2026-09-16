# Evidence nomination: cross-stage review and learning

Review ID: NOMINATION-T4-20260916. Updated: 2026-09-16T07:21:02+08:00.
Mode: ordinary staged-development audit. This log is not a formal release record
or a second accepted component map. Existing structural references include
`scan-logging/repository-regression`,
`component-map-lifecycle/direct-dependency-evidence-contract`, and
`reusable-audit-learning/evidence-linked-lessons`.

## Stage review

| Stage | Evidence and scope | Current conclusion / next gate |
| --- | --- | --- |
| T1 contracts | `18b52e62`, frozen schemas/golden vectors, 13 contract tests | Completed historical contract work; schema validity never proved hostile-filesystem safety. Keep raw examples unchanged. |
| T2 nominator | `0a28efdc`, 23 runtime tests, 301-test historical suite | Runtime feature work completed; T4 found publication/path race gaps beyond those fixtures. Earlier passes remain dated evidence. |
| T3 adapters | `46f08f5`, 27 compiler tests, 328-test historical suite | Reviewed candidate/handoff behavior implemented. Native input caps and entrypoint identity are preserved; T4 strengthens shared reads. |
| T4 adversarial audit | New security tests, Windows NTFS and native WSL/Linux runs, cross-platform byte probe | Superseded by T56 continuation: six-cell tests/probes passed at `1fcfbba`, with matching bytes within each Python/Unicode identity. See the candidate receipt; capability skips remain explicit. |
| T5 public journey | Runnable example, full guide, and fresh-process journey passed all six CI cells | T5 complete for the source candidate; literal Windows/Linux quickstarts also executed locally. |
| T6 release authority | Relocatable 0.10.0 source candidate prepared, with copied-package tests | Integrity is separate from release identity, exact map reconciliation, human acceptance, and a fresh formal record. Source package integrity/copy validation passed; exact map acceptance, unchanged reconciliation and verified formal append are now complete. Merge/release, activation and T7 remain separate. |
| T7 pilot | Protocol and 20-row intake template prepared; selection/labels are not frozen and pilot has not run | Freeze labels, inputs, comparator, and thresholds before measurements. No usefulness or scientific-benefit result exists yet. |

Historical report counts describe their original commits, not current-code
certification. Local evidence bundles are `nomination-t1-20260916` through
`nomination-t4-20260916` under the workspace artifact directory; they are not
part of a released package. T4 retains failed runs and per-cycle candidate
identities instead of replacing them with a final success banner.

## Lessons, causes, corrections, and limits

All entries share the review ID and timestamp above. Evidence-file hashes and
candidate identities are retained in the local `learning-evidence.json` and
`cycle-*.json` records. Test links identify source; persisted logs establish execution.

| ID / stages | Observed finding and verified cause | Correction / reusable rule | Evidence, applicability, and reversal condition |
| --- | --- | --- | --- |
| L1 / T1,T2,T4 | Canonical schema fixtures did not exercise read/write races. A temporary file could be replaced between close and hard-link publication. | Keep the written handle, check published identity/content, and report surviving artifacts on failure. Test interference at the actual operation boundary. | `security-red.log`, `test_temporary_substitution_cannot_report_success_with_wrong_bytes` in [security tests](../tests/test_evidence_nomination_security.py). Applies to exclusive local artifact publication; recheck when publication primitives change. It does not provide a whole-project transaction. |
| L2 / T2,T3,T4 | No-follow checks on the leaf did not protect native reads from a replaced parent. Windows directory handles did not always prevent the tested rename. | Share guarded readers; inspect opened handles and recheck ancestor identity before reading and before returning success. Reject hard-linked source aliases. | Parent-race and hard-link tests in [security tests](../tests/test_evidence_nomination_security.py), `security-cycle-1.log`. Windows evidence covers NTFS; broader filesystems and continuously hostile privileged writers are outside the demonstrated guarantee. |
| L3 / T1,T4 | A Unicode regression fixture used text-mode output, which introduced CRLF on Windows. The scanner correctly hashed those actual bytes. | Write byte-identity fixtures as explicit bytes; distinguish a fixture error from a product defect. Keep normalization-sensitive examples frozen. | `security-cycle-1.log`, `test_unicode_spellings_remain_distinct`. Applies to exact byte comparisons; text-mode application output can legitimately use platform line endings. |
| L4 / T3,T5,T6 | Earlier T3 review found an omitted native entrypoint identity and a generic guard reader exceeding the recorder's 5 MiB cap. | Bind delegated entrypoints and direct dependencies. Adapters retain the stricter authority's limits rather than silently replacing them. | T3 `native-entry-red/green.log`, `native-limit-red/green.log`, [compiler tests](../tests/test_evidence_nomination_compile.py). Reopen when dependencies or native contracts change. |
| L5 / T2,T4,T5 | The shared-reader refactor initially lacked isolated CLI import wiring. In-process tests already had the package path and hid the launch defect. | Test the real entrypoint in a fresh isolated process. Assert edit preconditions and inspect saved code when applying scripted substitutions. | T4 `windows-full-cycle-2.log` and `linux-full-cycle-2.log`; [platform probe](../tests/nomination_platform_probe.py). Applies to import/startup boundaries; unit tests still cover smaller algorithms. |
| L6 / all stages | Implementation, regression coverage, platform execution, acceptance, and pilot outcomes are different evidence dimensions. | Record each separately. A source change invalidates current-code replay while historical evidence keeps its identity. Keep unrun platform and human gates explicit. | [stage plan](SEARCH_ASSISTED_CLAIM_MAINTENANCE_PLAN.md), T1 through T4 records. Reopen if a completion statement loses its exact version/platform/scope. |

The reader's Windows handle comparison uses the volume/file identifiers described
by [Microsoft's handle-information API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle).
Its [file-information documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information)
also limits the uniqueness guarantee on ReFS; this work does not claim ReFS validation.

## Reusable checkpoints for later stages

1. Identify the stage's exact input/output authority and direct dependencies.
2. Link each claim to executed evidence with source identity, host platform,
   fixture scope, and known exceptions. Do not count reading a test as running it.
3. When an adapter or shared helper changes, check native caps, path rules,
   entrypoint imports, downstream guards, and package identities together.
4. Run a fresh-process journey plus targeted failure injection. Compare exact
   artifacts across compatible runtimes; different Unicode versions intentionally
   produce different finder identities.
5. Record the finding, cause certainty, correction, evidence, applicability, and
   reversal condition. Promote only checked procedures, not universal reliability.
6. Recheck active plan/docs/status rows, including superseded pending notices.
   Preserve frozen schemas, historical logs, and acceptance boundaries.

These checkpoints apply to T5 through T7 without asserting those stages have executed.
The existing [review-learning contract](../skills/analyze-project-claims/references/review-learning.md)
owns bounded rechecks and promotion rules. The personal claims overlay receives
a linked generic procedure; installed release files are not customized.

## T5/T6 continuation: 2026-09-16

Review ID: NOMINATION-T56-20260916. The first candidate is `a9cfe84`.
Its Windows full suite ran 349 tests: 346 passed and three skipped. The first
hosted Linux cells passed tests and the platform probe; macOS exposed the
case-capability fixture assumption described below. These are stage results,
not evidence of map acceptance or release. Exact final CI results supersede
these interim observations in the continuation report.

- The public journey now reaches a native candidate through fresh processes.
  The two-command PowerShell first result took about one second on the local
  host; this is CLI elapsed time, not a pilot reviewer-time measurement.
- A package-only copy originally lacked repository contracts, runtime imports,
  and receipt documentation. The runtime now lives inside the skill package;
  a copied-package regression checks identical nomination bytes from a neutral
  working directory. Packaged schemas relocate only native `$ref` paths, with
  a test preserving every other frozen byte. T1 originals remain unchanged.
- Changing SKILL.md intentionally stales old map identities. Runtime tests
  now rebind only explicit test-owned fixture copies, while the historical
  recorder rejection and real-map acceptance requirement remain enforced.
- The initial journey harness incorrectly added `-I` to the existing native
  reconciler. The documentation specifies ordinary Python for that entrypoint;
  the harness now preserves each command's actual startup contract.
- macOS CI falsified the fixture assumption that POSIX means case-sensitive
  storage. The collision test now detects actual case-distinct-name capability;
  capable filesystems still exercise rejection, while other filesystems report
  an explicit skip. OS names alone cannot establish filesystem behavior.
- Directory-wide map scope would bind generated example sidecars after a user
  runs the demo. The proposal scopes the example to its tracked source files,
  preserving output separation without weakening the native hash authority.

The personal staged-tooling workflow receives the filesystem-capability lesson.
All raw failures and execution evidence remain in the local T5/T6 artifact
bundles. No independent pilot labels or timings have been invented.

### Closure and supersession

The [six-cell candidate receipt](../validation/v0.10.0-candidate-validation-receipt.json)
for `1fcfbba` supersedes the interim platform notices above. Each cell ran 349
tests: Windows 346 passed/3 skipped, macOS 347/2, Linux 348/1. All five probe
hashes match across OS within Python 3.10 and separately within Python 3.12.
The original macOS failure remains preserved. All cells still refuse release
preflight with `MAP_IDENTITY_MISMATCH`; acceptance is not inferred from test success.

The literal example also exposed that the old Git ignore pattern covered only
root-level sidecars. It now covers nested example outputs, verified with actual
generated paths and `git status`. The proposed map scopes only tracked example
sources, so running the example cannot silently alter its structural snapshot.
That pre-acceptance notice is superseded by the [T6 acceptance receipt](../validation/v0.10.0-acceptance-receipt.json). T4/T5 are complete and T6 now has exact user-approved acceptance and a verified formal record;
T7 remains an unfrozen, unexecuted study awaiting independent human inputs.

## T6 acceptance and learning closure

Review ID: NOMINATION-T6-ACCEPTANCE-20260916. Timestamp: 2026-09-16T09:07:47+08:00.
The [acceptance receipt](../validation/v0.10.0-acceptance-receipt.json) records
exact candidate approval, accepted-map identity, prior-map archive, unchanged
reconciliation, preflight and the newly verified formal record/report. The
record's PARTIAL status preserves the untested usefulness claim; it is not a
structural verification failure. Earlier CI receipts remain immutable observations
of their earlier commits and do not describe the current accepted-map state.

The prepared command pointed from an isolated review directory directly at the
native accept operation. The native tool refused with `candidate must be inside
map-root/candidates`, before any acceptance. The correction copied the approved
candidate and its relative delta/history lineage into the required map directory,
checked identical raw SHA-256, and then used the native acceptance operation.
The original candidate and refusal log were retained. No fresh candidate was
generated or substituted under the old approval.

Reusable rule: check native destination/lineage constraints while preparing an
approval packet. On approval, stage exact bytes with no clobber, verify source
snapshots and the previously accepted map, then perform acceptance and unchanged
reconciliation. A changed candidate or source snapshot requires re-review; moving
identical approved bytes to the required native location does not invent a new
semantic approval. This procedure is saved in the personal staged-tooling overlay.

Active T6 notices were checked against their source authority. Unmapped stage
status and learning documents were updated; map-bound release checklists retain
their valid procedural requirements. Historical validation receipts and formal
records were not rewritten. T7 still needs independent labels and human timings.

### Accepted-tree validation closure

Timestamp: 2026-09-16T09:19:11+08:00. Review ID: NOMINATION-T6-ACCEPTANCE-20260916.
The [accepted-tree CI](https://github.com/Ian-Tseng/analyze-project-claims/actions/runs/35043189493) at
`2540dbff3576799a79ddad6e87e9c7a110cb2ec6` passed all six Windows/Linux/macOS
x Python 3.10/3.12 cells, including the complete suite, byte probe and map
preflight. The local Windows full suite also passed: 349 tests, three skipped.
T1 through T6 are complete within their recorded scope. The active plan and
development guide now link this observation; the PR description must reflect
the same accepted state. Earlier failed preflight receipts remain historical.
T7 is unexecuted and still requires independent labels and paired human timings.
The saved personal workflow is linked from the claims overlay under staged
evidence tooling; released skill files were not customized.

## Changelog coverage correction

Review ID: NOMINATION-CHANGELOG-20260916. Timestamp: 2026-09-16T09:32:58+08:00.

The preceding closure missed four active Unreleased changelog notices while
checking the stage plan and guide. CHANGELOG.md still described acceptance,
preflight and completed implementation tasks as pending. The wider pre-merge
scan found the conflict. The claim of no remaining in-scope conflicts at the
prior checkpoint was too broad; this finding reopens T6 source acceptance.

Correction: describe the implemented gates and locate dated outcomes in their
receipts and stage plan, rather than embedding changing pending statuses in
map-bound change descriptions. Released changelog sections, historical maps,
records and receipts remain unchanged. The only mapped source change is
CHANGELOG.md; runtime, package identities, contracts and tests are unchanged.

Workflow lesson: inventory root release documents as well as stage-specific
documents before declaring closure. Compare the inventory with map source
snapshots and inspect every active pending notice. Map-bound documentation
corrections require a new candidate even when executable behavior is unchanged.
The personal staged-tooling overlay now includes this explicit inventory step.
A walkthrough covers this missed changelog and the counterexample of a dated
released changelog entry, whose historical status must be preserved.

Pre-approval observation (superseded by the acceptance closure below): the old
accepted map and historical record were retained while the new map awaited exact
human approval. T7 still needs independent human study evidence.

The verification also observed that recorder preflight reports `ready` while
the reconciler reports CHANGELOG.md source drift. Preflight alone therefore
does not establish unchanged reconciliation for this case. Both gates must be
recorded independently; a ready preflight cannot substitute for exact acceptance.

### Changelog acceptance closure

Review ID: NOMINATION-CHANGELOG-20260916. Timestamp: 2026-09-16T09:41:43+08:00.
The user approved exact candidate `component-map-92872d9a90de`, SHA-256
`2d2163e5d7bb8d4883756f652e743976ec615916b34da7e84527450b754dd0c1`,
including conditional merge after passing checks. All 200 source snapshots were
rechecked before native acceptance. The [acceptance receipt](../validation/v0.10.0-changelog-acceptance-receipt.json)
records acceptance, `checked_unchanged` reconciliation and ready preflight.
The [fresh formal report](../validation/reports/20260916T014102515403Z-369e52b8.md) verifies; its PARTIAL
scan state preserves the untested human-usefulness claim. Previous accepted maps,
records and released changelog sections retain their original bytes.

The plan and development guide now reflect this accepted source correction.
The exact reusable update is applied in the personal claims overlay reference
`references/staged-evidence-tooling.md`, sections ?Root release documents in the
closure inventory? and its separate reconciliation/preflight check. The motivating
case and historical-entry exception are documented there. No installed release
was customized. T7 remains unexecuted; publication and activation are separate.
