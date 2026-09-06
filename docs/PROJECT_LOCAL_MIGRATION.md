# Migrate a project-local audit variant

A project-local skill can contain contracts beyond the published package.
Replacing it is safe only after reviewing its callers and those extra semantics.
This guide addresses the reference names and recorder command reported in
[issue #13](https://github.com/Ian-Tseng/analyze-project-claims/issues/13).
It does not certify that an unidentified local project has been migrated.

## Reference contracts

The v0.9.0 package does not include `references/formal-operators.md` or
`references/research-lifecycle-and-rag-audit.md`. Treat these names as variant
contracts until their actual contents and instruction routes are compared.
The published [logic-guided RAG audit contract](../skills/analyze-project-claims/references/logic-guided-rag-audit.md)
covers finite-domain operators, transition authorization, evidence flow, and
lifecycle gate separation. It is a comparison target, not a promised filename
alias or proof that every local requirement is preserved.

1. Record the exact project root, installed package revision/digest, instruction
   routes, launch scripts, and every referenced local resource. Preserve the
   original files and their hashes before editing.
2. Compare each local rule with the published contract. Record which rule is
   equivalent, different, or absent, together with its callers and intended
   authority. A matching filename or heading is insufficient.
3. Keep project-specific rules in project-owned documentation outside the
   installed package, with provenance and explicit links from project
   instructions. Point shared generic rules to the canonical installed skill.
   Do not insert private project material into a public upstream contribution.
4. Update the exact callers and instruction links together. Exercise their
   real audit path against bounded fixtures and check that reference resolution,
   domain definitions, gate separation, and output expectations still hold.
5. Retire a duplicate package only when no active process or registered future
   caller depends on its path. Preserve historical scan records and any pinned
   or modified installation until its owner authorizes replacement.

## Recorder compatibility and migration

In v0.9.0, the flag-only invocation is still supported for one compatibility
window. The top-level `--help` emphasizes the staged v2 interface; it does not
mean that the legacy dispatch has been removed. Existing v1-shaped input can
still be appended with:

```powershell
$Recorder = "<canonical-installed-skill>/scripts/record_scan.py"
py -3 $Recorder --record .\legacy-input.json --log-dir .\validation\history
```

The resulting v1 record is historical and `LEGACY_RECORD_UNBOUND`; it does not
acquire v2 evidence bindings merely because the current recorder wrote it.
The repository's `tests/test_record_scan.py` exercises this compatibility
command and append-only behavior. Do not assume compatibility with every
custom record shape or future release.

To migrate to v2, follow the
[evidence-bound record guide](../skills/analyze-project-claims/references/evidence-bound-audit-records.md):

1. Reconcile the project's component map and explicitly accept its reviewed
   candidate. Run `preflight` with the real project and map roots.
2. For an existing historical v1 record, run `draft-v2 --legacy-record PATH
   --map-root MAP --project-root PROJECT --output NEW_DRAFT`. For a new audit,
   use `init` with the same roots and a new output path.
3. Review the draft's untested claims, accepted component/element IDs, evidence,
   locators, and support/contradiction/limitation bindings. `draft-v2` copies
   prose, creates no evidence bindings, and selects no strongest safe claim.
4. Run `validate`, then `append` with `--record`, `--map-root`, `--project-root`,
   `--log-dir`, and `--report-dir`. Verify the emitted record and derived report
   with `verify`. Preserve the original v1 history unchanged.

Adding the word `append` to the old command is insufficient: v2 requires a
reviewed accepted map and a different record contract. Structural verification
also does not decide whether the evidence semantically supports each claim.

## Completion evidence

Record the source and destination revisions, reference comparison, exact
updated callers, fixture results, and remaining active dependencies in the
owning project's migration report. Upstream documentation and passing package
tests establish a supported procedure; only local caller validation establishes
that a particular project can retire its variant.
