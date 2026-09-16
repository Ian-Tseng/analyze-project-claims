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
| T4 adversarial audit | New security tests, Windows NTFS and native WSL/Linux runs, cross-platform byte probe | Local corrections implemented; final verification is recorded in the local T4 artifact bundle. macOS and Python 3.10 executions remain unrun. Do not mark the complete platform gate passed. |
| T5 public journey | Runnable example, full guide, and fresh-process journey implemented; final evidence pending | Run each documented command as a fresh isolated process before declaring the journey complete. |
| T6 release authority | Relocatable 0.10.0 source candidate prepared, with copied-package tests | Integrity is separate from release identity, exact map reconciliation, human acceptance, and a fresh formal record. All release gates remain pending. |
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
