# Claims-guided subagent mode

This optional mode delegates one substantial work unit at a time, then routes
its outcome to a separate `analyze-project-claims` reviewer. The coordinator
continues eligible work automatically and commits the affected working claims,
evidence links, limitations, and dependent report projections after review.
`done` records an execution outcome; only reviewed evidence can support a claim.

Use this mode when delegation and the underlying work are already authorized.
It extends the durable [controller](../scripts/long_running_controller.py) and its
[long-running contract](long-running-mode.md). The native host integration is
specified in [host protocol](subagent-host-protocol.md). This is an optional packaged helper; formal evidence-acceptance procedures remain unchanged.

Apply [evidence-guided agents](evidence-guided-agents.md) to every participating
role and include it with controlling files in `reviewer_sources`.

## Configure a goal

When initializing a new authorized goal, add `subagent_mode` and the action
claim fields to its normal manifest. Then retain that same goal, finite dispatch
budget, evidence inventory, and state directory throughout its execution.

There is currently no enable/migration command for an already initialized base
goal. Keep existing goals in base mode until an explicit migration is implemented.
Do not retrofit this configuration by editing journal events or initializing a
replacement state directory to reset progress, holds, or budgets.
A complete synthetic manifest and setup appear in the [startup example](#synthetic-startup-example).

`subagent_mode` contains exactly four fields: nonempty `authorization_ref`,
`reviewer_sources`, `claims`, and `reports`. Each claim has an `id`, `statement`,
`scope`, and optional acyclic `depends_on` list. Each report has exactly `id`,
`title`, and nonempty `claim_ids`; IDs match `[a-z][a-z0-9_-]{0,63}` and cannot
be reserved device names. All referenced claim IDs must exist.

Resolve the active skill at setup. Every reviewer source must be an existing
absolute file path. Include the active SKILL.md, applicable user instructions,
and referenced guides needed for this audit. The request binds their SHA-256
identities through `reviewer_contract.digest`, together with the running
controller, subagent module and agent-cleanup module. Hashes identify pinned bytes; the host must
actually invoke the skill and observe the review.

Declare all source evidence in the base manifest's project-relative `evidence`
list. Claim evidence may cite only those files, with the current SHA-256 and a
claim-specific locator. Keep the controller state and generated report
projections outside that list: generated reports do not supply their own support
and their regeneration must not create a source-change review loop.

Each action declares nonempty `affected_claims`, including hypotheses it tests.
Its `required_claims` are only genuine execution prerequisites, not every working
assumption or desired experimental result; they must be `supported` under the current
review. The controller also retains action dependencies, review clearances,
holds, repair limits, and pause checks. A worker cannot bypass a missing premise
by claiming its own proposed implementation is already supported.

An evidence-gathering or construction action may have `required_claims: []` only
with a substantive `premise_free_reason`. Explain why doing that bounded action
does not assume the untested conclusion. This allows testing an open hypothesis
without treating the hypothesis as established. Such work still declares affected
claims and receives review afterward.

## Review and update

Claims start `untested`; configuration is not evidence. Initial review establishes
which work can start. After each `done`, `failed`, or `uncertain` work result,
review every affected claim and its transitive dependents. Any declared source
evidence or reviewer-contract drift conservatively marks all claims for review. Every ID in `required_claim_updates` must receive an update;
an extra updated claim also requires updates to its dependent closure. All
`claim_dirty` entries must be resolved before any work proceeds, including
premise-free work. Preserve same-scope counterevidence and historical review results when replacing the
current working projection. Clearing dirty claims records a review; it does not
require promoting them to supported. An eligible investigation may proceed while
its target is untested or contradicted, with genuine prerequisites still enforced.

The reviewer uses exactly the installed skill's five statuses:

- `supported`: direct evidence matches the claim's stated scope.
- `partially supported`: direct evidence has material limitations.
- `contradicted`: same-scope counterevidence conflicts with the claim.
- `untested`: no direct test exists.
- `invalidly specified`: necessary protocol or scope definitions are missing.

Extend the normal review result with these fields:

```json
{
  "skill_invocation": {
    "skill": "analyze-project-claims",
    "contract_digest": "copy request.reviewer_contract.digest"
  },
  "claim_updates": [
    {
      "id": "C-IMPLEMENTATION",
      "status": "partially supported",
      "evidence": [
        {
          "path": "validation/acceptance-output.json",
          "locator": "cases.required_fields",
          "sha256": "copy the current digest for this declared source",
          "method": "executed_test",
          "relation": "supports"
        }
      ],
      "limitations": ["Only the persisted local acceptance cases were executed"],
      "rationale": "Recorded results cover the required fields but leave the boundary cases untested",
      "audit_refs": []
    }
  ]
}
```

This fragment accompanies, rather than replaces, `review_status`, `decision`,
`snapshot_digest`, `request_digest`, coverage, clearances, findings, and the other
base result fields. Evidence methods are `source_inspection`, `executed_test`,
`deterministic_replay`, and `not_tested`; relations are `supports`, `contradicts`,
`limits`, and `context`. `executed_test` cites persisted execution output, not
the test source. `not_tested` is context-only. A hash match does not establish
semantic support; the reviewer must inspect the exact cited location.

Every nonsupported status requires an explicit limitation. Supported claims need
a support link and cannot retain an unresolved contradiction link. Untested and
invalidly specified updates cannot assert support or contradiction links. If an update removes
a previous contradiction link, include `superseded_evidence` entries with
`evidence` equal to the complete old link and a nonempty `reason` explaining why
it is superseded. The journal retains the old review; an unexplained omission
cannot erase counterevidence. A supported dependent claim requires supported
premises, even when its own cited result looks positive.

The reviewer is read-only. It returns its result to the coordinator, which uses
`finish` to validate and commit working claims and regenerate declared report
projections in the same state directory. Workers return outcomes and evidence;
they cannot clear their own claims or edit the controller journal. Report
projections retain the configured claims, their scope, evidence, limitations,
formal audit references, and the distinction between pending review and the
last reviewed assessment. Claim dependencies remain declared in the manifest.

The journal-backed `working_claims` state is the operational authority. Read
`<state>/reports/current.json` to locate the digest-named report revision and
its per-file hashes. That revision contains `claims.json` and one `<id>.md` for
each configured report. The controller writes and verifies these projections,
then commits the pointer last. They are rebuildable views of the retained state;
manually editing them does not update a claim.

These are working orchestration records, not accepted component maps or formal
skill audit records. For substantive formal scans, follow the installed skill's
engine verification, component reconciliation, evidence-bound record procedures,
and applicable overlays. A read-only reviewer returns proposed formal artifacts;
the coordinator persists them only within existing authority. Link actual formal
records using `audit_refs`. Missing formal records stay explicit. Only the
relevant human authority can accept an exact component-map candidate.

## Continuation and limits

The host follows `next -> check -> spawn waiting agent -> bind-agent -> check -> START -> wait/recover -> finish
-> next`. One persisted token covers the active worker or reviewer. This version
supports sequential delegation; it does not run competing work mutations in
parallel. Calling `next` while a token is in flight recovers that request and must
never spawn a duplicate worker.

Automatic review means the authorized host keeps this loop running after each
substantial work unit; the Python controller cannot invoke a model or wake an
idle host by itself. No scheduler, service, background conversation, model
switching, or new external execution authority is installed by this mode. Preserve finite budgets,
user pauses, uncertain outcomes, and the existing bounded repair history across
handoffs. Stop only under the base goal's actual completion or stopping rules.

Use the native host protocol or an adapter implementing the complete skill
invocation, review, and claim-update contract. A tool-disabled adapter or a
closed schema without claim updates cannot satisfy this contract.

Protocol validation and fixture tests establish bounded controller behavior.
They do not prove that a host invoked the skill, that semantic reviews are always
correct, or that any scientific or product acceptance gate passed. Report those
observations separately when validating a deployment of this mode.


Configured reviewer paths pin specific files. Activating a different skill version
at a new path cannot be discovered by hashing the old files. The host must resolve
the active skill before each invocation and fail closed if it differs from the
configured contract; include an activation manifest where the host provides one.
This mode does not infer a new active version from a successful old hash check.


## Freshness of saved reports

`status` and report regeneration sample the declared evidence and reviewer contract.
The returned `freshness` and report projection distinguish CURRENT, STALE and UNKNOWN
source currency from the last recorded claim statuses. `review_required_claims`
includes all claims on drift or an unreadable source. Historical `complete` remains
a recorded decision; `freshness.completion_current` states whether it still applies
at the sampled identities. CURRENT identity alone does not resolve pending review.

An observation does not alter pending tokens, budgets, holds, pauses or accepted
claim decisions. `check` still blocks a stale worker; recover its existing token
before continuing. Saved reports describe the last sampled identities, not continuous
monitoring. Read status again before relying on their freshness. Earlier report
revisions remain historical evidence.

## Validation scope

Deterministic tests cover controller invariants and synthetic fixtures. A native
worker/reviewer cycle passed in the precursor local installation. The packaged
port has not yet been activated and exercised through a fresh native host cycle;
that observation cannot be transferred from the precursor by changing paths or
reusing its result digests. Neither source provenance nor tests establish general
review accuracy, reliability, scientific benefit, or publication eligibility.
See the [design-source log](subagent-design-sources.md).

## Synthetic startup example

Run in a writable project directory with Python 3.10+. Commands below use `python3`;
on Windows use `py -3`. Save this as `setup_demo.py` and invoke it with the exact
authorizing instruction as its first argument and the resolved active skill directory as its second. It creates a new `claims-demo`
fixture and refuses to replace an existing one. Keep this new state directory
for the whole attempt; do not recreate it to replenish budgets.

```python
import json
from pathlib import Path
import sys

if len(sys.argv) != 3 or not sys.argv[1].strip():
    raise SystemExit("Supply actual delegation authority and the absolute active skill directory")
authority = sys.argv[1]
skill = Path(sys.argv[2]).resolve(strict=True)
sources = [skill / "SKILL.md"] + [skill / "references" / name for name in (
    "review-learning.md", "evidence-guided-agents.md", "long-running-mode.md", "subagent-mode.md",
    "subagent-host-protocol.md")]
assert all(path.is_file() for path in sources)
project = (Path.cwd() / "claims-demo").resolve()
project.mkdir(exist_ok=False)
(project / "spec.json").write_text(
    json.dumps({"input": 9, "operation": "square", "expected_output": 81}),
    encoding="utf-8")
goal = {
    "goal_id": "synthetic-square",
    "goal_revision": "1",
    "objective": "Run one delegated fixture and review its observed output",
    "authorization_ref": authority,
    "project_root": str(project),
    "evidence": ["spec.json", "output.json"],
    "success_criteria": ["The worker output is 81 and both scoped claims were reviewed"],
    "max_dispatches": 8,
    "actions": [{
        "id": "square", "kind": "work",
        "instruction": "Read spec.json; write only output.json with input squared under key output",
        "required_claims": ["C-PROTOCOL"],
        "affected_claims": ["C-OUTPUT"]
    }],
    "subagent_mode": {
        "authorization_ref": authority,
        "reviewer_sources": [str(path) for path in sources],
        "claims": [
            {"id": "C-PROTOCOL", "statement": "The fixture declares input 9, square operation and expected output 81",
             "scope": "spec.json, one synthetic fixture", "depends_on": []},
            {"id": "C-OUTPUT", "statement": "The worker produced output 81",
             "scope": "output.json for this single fixture", "depends_on": ["C-PROTOCOL"]}
        ],
        "reports": [{"id": "progress", "title": "Synthetic fixture evidence",
                     "claim_ids": ["C-PROTOCOL", "C-OUTPUT"]}]
    }
}
(project / "goal.json").write_text(json.dumps(goal, indent=2), encoding="utf-8")
```

Resolve the active skill before real use. This setup binds the supplied directory; it does not activate a different
installation in your host. Add
applicable user instructions and referenced formal-audit guides before `init`.
Review source paths must be existing absolute files. A version activated at a
new path cannot be discovered by hashing an old path.

```text
python3 setup_demo.py "ACTUAL DELEGATION AUTHORITY" /absolute/path/to/active-skill
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state init --config claims-demo/goal.json
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state next
```

Replace `/absolute/path/to/active-skill` with the actual path (quote paths containing spaces).
The first `next` persists a reviewer request. It does not run a reviewer.
The host retains the complete returned token and request, then performs:

```text
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state check --token TOKEN
# Native host: spawn the appropriate agent, instructed to wait for START.
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state bind-agent --token TOKEN --agent-id OBSERVED_HOST_AGENT_ID
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state check --token TOKEN
# Native host: send START to this bound agent only on READY; wait for its actual result.
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state finish --token TOKEN --result result.json
# Native host: inspect completion, run agent-cleanup with fresh observations,
# and close eligible owned agents if supported, preserving pending claims review.
python3 /absolute/path/to/active-skill/scripts/long_running_controller.py --state claims-demo/state next
```

Substitute values returned by the actual host/controller, never invented IDs.
The initial reviewer invokes the active skill, inspects `spec.json`, and may
support C-PROTOCOL while retaining C-OUTPUT as untested. It returns the full
[base review result](long-running-mode.md#base-review-result)
and [claim updates](#review-and-update).
Copy all three binding digests programmatically from its checked request.
A `skill_invocation` declaration is attestation; the host must observe that the
reviewer actually invoked the skill and inspected the claimed sources.

After initial clearance, the next eligible request is the worker. Its result
may be `{"status":"done","evidence":["output.json"]}` only if that outcome
was observed. Completing it schedules a new claims review automatically.
The reviewer inspects the real output, updates affected claims and dependent
claims with current source hashes, locators, limitations and rationale, then
applies the complete goal-completion gate. No example result substitutes for
that actual review. `failed` and `uncertain` outcomes also schedule review;
they are not evidence of completion or permission to repeat unknown work.

Use the [completed-agent lifecycle check](subagent-host-protocol.md#check-completion-and-release-host-resources) after results and before new dispatch. The `agent-cleanup` command produces a conservative plan; actual host closure is capability-dependent and never deletes evidence or clears pending claims review.
