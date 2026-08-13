# Agent Maintainer for Internal Reports

This optional owner workflow turns one reviewed public internal-report issue
into a validated draft pull request. It does not merge, release, close the
issue, or update users.

This is the operator runbook for `Ian-Tseng/analyze-project-claims`. To adapt
the architecture to another repository, use the
[Reusable GitHub Agent-Maintainer Guide](GITHUB_AGENT_MAINTAINER_GUIDE.md).

```text
bounded public report
  -> owner applies agent-ready
  -> exact-schema intake removes unrelated issue data
  -> Codex prepares a candidate without GitHub write credentials
  -> a fresh secret-free job applies and tests the exact patch
  -> a final non-executing job publishes a new draft PR
  -> owner review, release, and installed-update verification
```

Private owner-API reports are intentionally outside this workflow. Do not send
them to OpenAI or another processor without a new explicit user consent and a
documented data-processing policy.

## One-time owner setup

1. Create the `agent-ready` label. Only the repository owner should apply it:

   ```powershell
   gh label create agent-ready `
     --repo Ian-Tseng/analyze-project-claims `
     --color 1d76db `
     --description "Owner-approved bounded report for isolated candidate repair"
   ```

2. Add an `OPENAI_API_KEY` Actions secret. Use a dedicated project key with a
   spend limit and rotation policy. The Codex job receives no repository write
   token.

3. Create a short-lived, fine-grained GitHub personal access token named
   `AGENT_MAINTAINER_TOKEN`. Limit it to this repository and grant only:

   - Contents: read and write;
   - Issues: read and write;
   - Pull requests: read and write.

   Store it as an Actions secret. This separate token is used only after the
   patch has passed isolated validation. A normal `GITHUB_TOKEN` push would not
   start the repository's ordinary push and pull-request workflows, so the
   publisher uses this narrowly scoped token instead.

4. Require the normal `validate` workflow and owner review before merge. Keep
   draft pull requests non-mergeable until those controls pass.

The implementation follows the current official
[Codex GitHub Action guide](https://learn.chatgpt.com/docs/github-action): it
pins `openai/codex-action` to the commit behind the reviewed `v1` tag, uses
the `:workspace` permission profile, runs Codex as a separate unprivileged
account, allowlists the owner, and gives the Codex job no repository write
permission.

## File map

Keep this table synchronized whenever the workflow boundary changes. It is a
reader aid, not a second component-map authority; the accepted machine map
under `validation/component-map/` retains that role.

| Responsibility | Files | Authority boundary |
|---|---|---|
| Trigger and job privileges | `.github/workflows/agent-maintainer.yml` | Trusted default-branch workflow |
| Ordinary repository CI | `.github/workflows/validate.yml` | Independent push and pull-request validation |
| Agent instructions | `.github/codex/prompts/resolve-internal-report.md` | Trusted prompt; report fields remain untrusted |
| Exact issue intake | `maintainer_service/intake.py` | Converts one disclosed public report to a minimal task |
| Candidate allowlist | `maintainer_service/patch_guard.py` | Copied before Codex and reused without importing candidate code |
| Post-agent collection | `maintainer_service/post_agent.sh` | Installed root-owned before privilege drop; uses a protected Git snapshot, a new alternate index, and a clean process environment |
| Public report producer | `skills/analyze-project-claims/scripts/problem_report.py` | Consent, redaction, exact body, and processing disclosure |
| Package identity | `VERSION`, `CITATION.cff`, package version, package manifest | Synchronized release candidate identity |
| Regression contracts | `tests/test_agent_maintainer.py`, `tests/test_problem_report.py` | Local deterministic boundary evidence |
| Owner operations | `docs/AGENT_MAINTAINER.md`, `docs/PROBLEM_REPORTING.md`, `PUBLISHING.md` | Setup, triage, review, release, and evidence limits |

The GitHub issue, candidate artifact, branch, pull request, release, installed
copy, and fresh activation are separate lifecycle objects. A later object does
not retroactively prove an earlier or downstream state.

## Triage and start a candidate

Review the issue first. It is eligible only when all of these are true:

- it is an open issue, not a pull request;
- the body exactly matches the bounded Markdown emitted by
  `problem_report.py`;
- its fixed disclosure says the public report may be sent to OpenAI Codex;
- its event code is known and is not `REPORTING_E2E_TEST`;
- the title, report classification, repository, issue number, and URL agree;
- `Ian-Tseng` applies the exact `agent-ready` label.

Then apply the label:

```powershell
gh issue edit <number> `
  --repo Ian-Tseng/analyze-project-claims `
  --add-label agent-ready
```

The label is authorization for one isolated candidate attempt only. It is not
authorization to merge, publish, call the report fixed, close it, or process a
private API record.

## What the automation enforces

The prepare job binds the issue event to one immutable default-branch commit,
records that SHA in the task, and requires every downstream checkout to use
the same SHA. The intake forwards only the fixed report fields required for diagnosis. It
does not forward the raw issue body, comments, reporter identity, or
installation UUID. All forwarded strings remain explicitly untrusted.

The patch guard permits bounded UTF-8 text changes only in the packaged skill,
tests, examples, public docs, README, and synchronized version metadata. It
rejects workflow, maintainer-service, reporting-service, analytics-service,
security, publishing, validation-authority, agent-metadata, updater,
problem-reporting client, installation-analytics client, privacy-schema,
binary, symlink, deletion, rename, copy, oversized, and cross-skill changes. Reports
touching those sensitive surfaces require manual owner repair.

The official Codex Action guide recommends placing Codex last in a job. Patch
capture necessarily requires a following step, so the workflow uses the
guide's separate unprivileged-user strategy. Before Codex runs, it installs
the collector, guard, and complete checkout Git metadata snapshot as
root-owned files. Afterward, the runner terminates every process owned by the
agent account and invokes the collector as root through an absolute shell
path. The collector clears interpreter and Git influence variables, uses
absolute system tools, disables hooks and external diffs, and builds a new
alternate index from the protected original `HEAD`. Candidate changes to the
checkout's own `.git` directory therefore cannot change the captured base or
index. The workflow does not retain the agent's free-form final message. The
candidate artifact is still untrusted and is applied again only in a fresh
no-secret validation job.

If packaged skill bytes change, the candidate must bump exactly the next patch
version and synchronize `VERSION`, `CITATION.cff`, package version, and package
manifest. A fresh job with no secrets or write token applies the exact patch,
runs the full standard-library suite, and verifies package identity. The
publisher applies the same digest in a fresh checkout and does not execute
candidate code.

## Owner review and completion

The successful output is a new
`agent/issue-<number>-run-<run-id>-<attempt>` branch and a draft pull request.
The GitHub run identity makes every attempt a new branch, so retries never
overwrite earlier review evidence and never require a force-push.

Before marking the pull request ready:

1. verify the issue is an actual product defect;
2. review the regression test and smallest-fix claim;
3. inspect every changed path and the patch-guard artifact;
4. require the ordinary multi-platform CI run;
5. merge through the normal protected-branch process;
6. publish a new version without moving an old tag;
7. verify an older managed install updates and a fresh invocation loads it;
8. record the fixed version, then close the report.

Users with separately enabled managed updates can receive the released version
on a later invocation. A draft, merge, passing test, or even release by itself
does not prove that any user installed or activated the repair.

## Failures and recovery

- Intake rejection means the actor, label, repository, issue identity, title,
  or exact report form did not match. Do not loosen the parser; regenerate a
  current report.
- No candidate or a guard rejection means Codex could not produce an eligible
  patch. Inspect the workflow output and repair manually.
- Test or package verification failure means no publishing job runs.
- Missing secrets fail before publication. Add or rotate the exact scoped
  secret; do not replace it with a broad long-lived token.
- A retry publishes a separate run-scoped candidate branch rather than
  overwriting earlier evidence.
- A published draft remains untrusted until human review and ordinary CI pass.

Workflow logs and seven-day candidate artifacts are operational evidence, not
proof that the issue was resolved. The GitHub issue and pull request remain the
owner's durable audit trail.

## Local end-to-end contract

`tests/test_agent_maintainer.py` includes a no-network pipeline test. It builds
an exact disclosed report, performs owner-gated intake, observes a red
regression, creates an eligible patch, records its SHA-256 identity, applies
that exact patch to a fresh checkout, re-runs the trusted guard, and observes
the focused test pass. This validates local handoff semantics only. It does not
call OpenAI, create a GitHub issue or pull request, exercise repository secrets,
or prove the hosted workflow until a separately authorized live canary is
observed.

The dated commands, observations, and unproved states are retained in the
[Agent-Maintainer Local E2E Log](AGENT_MAINTAINER_E2E_LOG.md).
