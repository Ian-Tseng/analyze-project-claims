# Recheck inconsistencies and retain validated lessons

Read this packaged guide from the skill workflow after a
substantive audit, authorized repair, or change to controlling evidence. It
supplements the active skill's checks; it does not replace its evidence
contracts, maintenance, receipt, acceptance, or authorization rules.

## Recheck within the original scope

1. Identify the changed source, evidence, definition, or decision and its
   dependent active surfaces. Use the existing artifact inventory or claim map;
   do not expand a local edit into unrelated work.
2. Recheck semantic relationships as well as wording: definitions, inputs and
   outputs, scope, evidence and counterevidence, lifecycle states, provenance,
   and dependent decisions. Classify each mismatch before choosing a repair.
3. When repairs are authorized, correct the active authority, synchronize its
   dependents, rebuild affected outputs, and reload the actual saved artifacts.
   Preserve historical evidence and protected author or acceptance states.
4. Any repair invalidates the preceding pass. Rerun the complete applicable
   checks over the authorized scope, including its affected dependencies and
   required visual checks. A local wording scan alone cannot close semantic,
   scientific, or generated-artifact findings.
5. Close only after a complete pass needs no repair and leaves no unresolved
   material in-scope inconsistency. Use the host workflow's readiness statuses;
   missing evidence or a required external action remains explicitly open.

Use at most three repair-and-recheck cycles per invocation, or the host's
stricter bound. Stop earlier if the finding set and candidate are unchanged,
a previous candidate recurs, repairs oscillate, or progress requires missing
evidence or authority. Record remaining findings and the concrete resumption
condition. Do not reset the counter through recursive skills or automatic
restarts. A cycle limit is a stopping condition, never evidence of convergence.

For read-only work, return findings and proposed lessons without writing or
repairing. Existing task authorization continues to apply; this guide neither
requires repeat confirmation for authorized edits nor grants unrelated writes.

## Record the lesson where its evidence already lives

Reuse the project's existing audit, decision, or major-revision record and ID.
For a formal claims scan, link its evidence-bound record and accepted component
IDs; a learning note must not become a second claims authority. If authorized
and no suitable record exists, create a small project learning log only when
there is a useful lesson to retain. Do not manufacture entries for clean runs.

Record:

`ID and timestamp with UTC offset -> finding -> evidence locator and version/hash
-> cause (verified or hypothesized) -> correction -> verification and limits
-> applicability and exceptions -> proposed reusable guidance
-> destination/section and promotion state -> unresolved issue or reversal trigger`

Keep mutable prose, measurements, private evidence, and project-specific names
in the project record. Reusable guidance should retain the decision-changing
relationship, not copy that material. Preserve earlier evidence and append a
supersession link when a conclusion changes.

## Decide whether and where to promote

| Decision | Action |
| --- | --- |
| Is the cause uncertain or the correction unverified? | Keep a provisional lesson with the missing check; do not make it a rule. |
| Is this a project fact, exception, or user preference? | Update the relevant project Markdown contract or decision record within its scope. |
| Does the lesson change a choice under identifiable conditions? | Update the existing decision flow with trigger, evidence, branches, action, success/failure signal, and reversal condition. |
| Does it establish a repeatable procedure useful across tasks? | Update the appropriate local workflow/reference, with applicability and limits. |
| Does existing guidance already cover it? | Repair the missing link, ambiguous trigger, or failed execution step; do not duplicate the rule. |
| Does new evidence contradict an earlier lesson? | Reopen the lesson, narrow or supersede the active guidance, and retain its history. |

A demonstrated failure with a verified correction can justify a narrowly scoped
procedure. Repeated observations of the same source are not independent
validation. Broader empirical claims require evidence covering the broader
scope; recurrence alone does not establish causality or general reliability.

When authorized to retain reusable lessons, make the supported local update
during the task, link it where the relevant future invocation will read it,
and record the exact destination. Otherwise return a concrete proposed change.
For installed managed skills, use supported local customization files; do not
modify installed release entrypoints, metadata, manifests, or updater authority.
For explicitly authorized upstream updates, edit the source repository and
follow its contribution and package-validation rules. Local learning does
not authorize publishing feedback or accepting evidence on a user's behalf.

## Verify the guidance update

Read the revised guidance against the host workflow and nearby rules. Check
for duplicate authority, contradictory branches, broken links, and lost scope
or stop conditions. For a changed decision flow, walk through the motivating
case and a plausible exception or counterexample; record this as a decision
walkthrough, not an executed test or independent evaluation. Use meaningful
behavioral checks when a changed executable procedure warrants them, without
adding wording-only tests for prose edits.

On later relevant invocations, read the linked guidance and reopen it when its
assumptions, evidence, or authority no longer hold. Report separately what was
fixed, what remains open, what was learned, and which guidance was actually
updated. Do not describe a proposal as installed or a past pass as current.
