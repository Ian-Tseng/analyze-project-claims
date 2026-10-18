# Label objectives and link their claims

Make objectives explicit in the existing project claim or decision record. An objective describes a desired outcome;
a claim is a proposition assessed against evidence. Keep them separate.

Use a stable objective ID such as `O1` and a short outcome label. Reuse existing
objective IDs and records; do not introduce a competing ledger. A quick audit
may use one concise objective entry. Add subobjectives only when they clarify
distinct outcomes or dependencies; ordinary work units need not become objectives.

Record, at the lightest sufficient depth:

- Objective ID, outcome label, scope, and the user instruction or agreed source
  establishing the objective. Mark inferred objectives as provisional.
- Observable success criteria and the evidence needed to assess each criterion.
- Linked claim IDs and their roles: execution prerequisite, hypothesis being
  investigated, or result claim. A link alone does not make a claim a prerequisite.
- Parent objective and dependency IDs where applicable; identify which outcomes
  and integration checks are required for the parent's completion.
- Objective progress, current evidence, unresolved criteria or blockers, and the
  next eligible action. Keep scientific support and human acceptance separate.

Use descriptive progress labels such as planned, active, blocked, completed,
paused, or superseded in the project record, respecting any existing schema.
These labels are not claim-support states or commands to a runtime controller.
A blocked objective needs a concrete blocker and resumption condition; it does
not automatically block independent eligible work. Preserve user pause authority
and the host's separate goal-status rules.

After substantive work, trace changed evidence through linked claims to affected
objectives, dependencies, decisions and reports. Complete an objective only when
its agreed criteria are met by evidence within the stated scope, including any
required integration or acceptance checks. A completed task, supported claim, or
completed child objective alone does not establish parent completion. Preserve
uncertainty and counterevidence; do not require all investigated claims to become
supported before an investigation objective can be completed.

For example, `O1: Determine whether retrieval improves accuracy under protocol P`
can be completed with a valid negative result if the agreed investigation and
reporting criteria are met. The linked benefit claim remains contradicted or
otherwise classified by the actual evidence. Conversely, a completed experiment
with an inconclusive result does not satisfy an objective whose agreed criterion
requires a determinate answer. If the objective was to conduct and report a
bounded investigation, an inconclusive result may meet that different criterion.

Retain criterion revisions with their source, reason, and affected dependencies;
never weaken criteria merely to declare success. Keep superseded objectives and
historical evidence. This guidance adds no controller fields, journal migration,
new execution authority, or formal evidence acceptance.
