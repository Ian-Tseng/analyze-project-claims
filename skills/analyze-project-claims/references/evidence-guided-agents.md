# Evidence-guided work across agent roles

Use this contract for the parent, planners, workers and reviewers participating
in this skill's workflow, including inline work outside controller mode. A host
may adopt it as general agent guidance; installing the skill alone does not add
a global hook or prove that unrelated agents follow it.

Base work on current claims and available evidence. Claims may be provisional:
there is no requirement to prove every assumption before starting authorized
work. Identify uncertainty, what observation would change the conclusion, and
which decisions depend on it. Test competing explanations rather than only
seeking confirmation. Inspect inherited source evidence where a decision depends
on it; another agent's assurance or an old PASS is not proof.

When observations support, qualify or contradict a claim, update its scope and
status, evidence links, counterevidence, limitations and dependent plans/reports.
Preserve previous assessments as history. An inconclusive check stays uncertain;
a failed process does not itself refute a scientific hypothesis. A negative
result can complete a goal framed as determining an answer, but does not justify
rewriting agreed delivery criteria or claiming a benefit.

After a substantive done, failed or uncertain work unit, the coordinator ensures
one claims review before dependent work continues. In controller subagent mode,
finish the worker token and use the separate reviewer. Workers return evidence
and proposed changes; they do not approve their own claims or edit shared state.
For inline work, the parent performs the review. The coordinator serializes
shared updates. A review's own record update does not trigger endless re-review.
Include this contract and scoped claim/evidence context in delegated handoffs.

Distinguish hypotheses under investigation (`affected_claims`) from genuine
execution prerequisites (`required_claims`). Only declared required claims need
current support before that action. An experiment's desired result is normally
a target, not a prerequisite. With no required claims, explain the authorized
investigation in `premise_free_reason`. All controller actions still require
review: clearing `claim_dirty` means assessment is recorded, not that every
claim became supported. Review may retain an untested or contradicted target.

Include applicable controlling instruction files explicitly in `reviewer_sources`:
the active skill, this guide, selected mode/host guides and applicable user
instructions. Hashing a document does not transitively hash linked files. Retain
existing journals and use supported revision procedures; never replace binding
digests on old requests or reset history to hide changed instructions.

Use [review-learning](review-learning.md#repair-cycle-budget-and-adaptation) for
the 32-cycle repair/recheck default and evidence-based prospective adjustments.
Preserve user budgets, pauses, execution authority and formal acceptance rules.
A skill invocation is not independent replication or proof of scientific benefit.
