# Reusable GitHub Agent-Maintainer Guide

This guide adapts this repository's owner-gated repair workflow to another
GitHub-distributed tool, CLI, plugin, SDK, or agent skill. It turns one
reviewed, bounded public report into a tested draft pull request. It does not
merge, release, close the report, or update installed copies.

Use it only for reports whose public visibility and external processing were
disclosed before submission. Keep confidential reports in a private owner
service unless users separately consent to another processor.

## Lifecycle contract

```text
submitted report -> owner-triaged report -> isolated candidate
-> independently validated patch -> draft pull request -> reviewed merge
-> immutable versioned release -> verified installed replacement
-> fresh activation
```

Each arrow needs its own evidence. A passing candidate is not a release, and a
release is not proof that an installed copy updated.

## Parameter sheet

| Parameter | This repository | Reuse decision |
|---|---|---|
| Canonical repository | `Ian-Tseng/analyze-project-claims` | Exact `owner/repository` |
| Authorized labeler | `Ian-Tseng` | One owner or a small reviewed allowlist |
| Trigger label | `agent-ready` | Dedicated owner-only label |
| Package root | `skills/analyze-project-claims` | Only discoverable package tree |
| Candidate prefix | `agent/issue-` | Prefix combined with issue, run ID, and attempt |
| Report producer | `problem_report.py` | Exact bounded schema and disclosure |
| Normal CI | `validate` workflow | Required independent checks |
| Version identity | four synchronized files | Repository release identity set |
| Allowed paths | skill, tests, examples, public docs | Smallest useful repair surface |
| Denied paths | control planes and release authority | Security boundary |
| Validation | unit suite and package verification | Secret-free deterministic commands |

Replace and test every value for the destination repository.

## Reusable architecture

Keep four privilege zones:

1. **Intake** emits only validated report fields.
2. **Candidate preparation** gives the agent no GitHub write credential.
3. **Fresh validation** applies the exact patch in a new secret-free checkout.
4. **Draft publication** receives only the validated patch and a narrowly
   scoped, expiring token; it does not execute candidate code.

Treat report fields and candidate files as untrusted. Pin every third-party
Action to a reviewed full commit SHA. Install post-agent collectors and guards
before privilege reduction, protect their code and base Git identity from the
candidate, and re-run the guard in fresh validation.

Bind all jobs to the event's immutable default-branch SHA. Name each candidate
branch with the issue number, GitHub run ID, and run attempt. This preserves
every artifact, makes retries explicit, and avoids force-pushing.

## Adopt it in another repository

1. Copy and rename the roles in
   `.github/workflows/agent-maintainer.yml`,
   `.github/codex/prompts/resolve-internal-report.md`,
   `maintainer_service/intake.py`, `maintainer_service/patch_guard.py`,
   `maintainer_service/post_agent.sh`, and
   `tests/test_agent_maintainer.py`.
2. Replace the repository, owner, package name, label, version identity, and
   branch prefix.
3. Define an exact versioned report schema. Reject unknown fields, bound every
   value, exclude secrets and user project content, use fixed event codes, and
   disclose the named agent provider in the public preview.
4. Default-deny credentials, CI, reporting and analytics clients, guards,
   release scripts, security policy, validation authority, binaries, symlinks,
   deletions, renames, and oversized changes.
5. Define one release-identity transaction when package bytes change. This
   skill synchronizes `VERSION`, `CITATION.cff`, package version, and
   package manifest at exactly the next patch version.
6. Create the owner-only label:

   ```powershell
   gh label create agent-ready --repo OWNER/REPOSITORY --color 1d76db --description "Owner-approved bounded report for isolated candidate repair"
   ```

7. Add `OPENAI_API_KEY` as an Actions secret using a dedicated,
   limited-budget project key. Add a separate expiring fine-grained token for
   draft publication with minimum repository permissions. Never print either
   value, commit it, store it in an artifact, or pass it to a test job.
8. Protect the default branch, require normal CI and human review, keep drafts
   non-mergeable, and protect release tags where supported.
9. Run a no-network local pipeline before enabling the label. Then run one
   harmless live canary clearly marked as a test. Record event, run, patch
   digest, PR, CI commit, release, installed version, and activation separately.

## Required tests

Test exact actor and label authorization; edited, malformed, undisclosed,
private, and synthetic-report rejection; intake minimization; absence of agent
write credentials; full-SHA Action pins; control-plane denial; exact patch
identity; fresh secret-free validation; draft-only publication; branch
collision refusal; complete version transactions; and absence of merge,
release, issue-close, or user-update actions.

Also run the ordinary full suite and package-integrity check.

## Operations and recovery

Apply the label only after human triage. If intake or the guard rejects the
attempt, keep the policy strict and repair manually or regenerate the report.
If validation fails, do not publish. Inspect an existing branch before
deliberately removing or renaming it; never force-push over evidence.

After review and normal CI, use the protected release process. Users receive
the fix only through their separately consented update mechanism. Record the
installed postcondition and a new host invocation before completion.

## Evidence boundary

A local simulation establishes deterministic handoff and guard behavior. A
hosted canary establishes one configured GitHub path. Neither proves broad
customer delivery, cross-platform behavior, provider availability, security
against every attacker, or that any user installed the release.

