# Managed Fleet Operations

## Authority model

Local update maintenance, bounded quality intake, repository repair, evidence
acceptance, and release are separate authority planes. Producer skills may ask
their native installer to replace one verified installation after user consent.
They emit content-free outcome receipts locally. `analyze-project-claims` may
turn a material receipt into a proposal, but a public issue still requires
explicit preview and confirmation.

The managed GitHub workflow begins only when `Ian-Tseng` applies the exact
`managed-repair-ready` label. That label establishes triage eligibility, not
repair or write authorization. `managed-repair-agent` approves isolated model
execution. `managed-repair-publish` separately approves draft publication.
Edits to issue body, labels, updated time, policy, base SHA, workflow SHA, or
expiry invalidate the attempt during live-state verification.

## Hosted provisioning checklist

For each producer repository:

1. Create both environments and require an owner reviewer. Disable admin bypass
   where the repository plan supports it and do not permit self-review.
2. Add only the repository-scoped `OPENAI_API_KEY` secret. Do not use
   `secrets: inherit` or a fleet-wide publication token.
3. Permit GitHub Actions to create pull requests. The caller grants the maximum
   token permissions; the reusable workflow reduces them per job.
4. Create the `managed-repair-ready` label, but do not apply it until the policy
   and caller are on the default branch.
5. Confirm the caller and policy contain the same reviewed full workflow SHA.
6. Run `workflow_dispatch` with `dry_run: true`. A dry run must stop after
   bounded intake and must not start the agent or publish job.

Hosted settings are external state. Record the repository, environment reviewer
IDs, protection read-back, PR setting, secret name (never its value), workflow
run URL, exact workflow SHA, and observation time in the canary evidence.

### Reusable-workflow identity

Do not use `github.workflow_sha` as the reusable-workflow identity. In a called
workflow GitHub resolves that context to the caller workflow commit, not the
central commit named after `@` in `uses`. The thin caller must repeat the same
reviewed central commit in three places: the `uses` ref, the `workflow-sha`
input, and `.github/managed-skill-policy.json`. Intake rejects any disagreement
before agent execution, artifact publication, or repository writes.

The first method dry run on 2026-08-20 demonstrated this fail-closed boundary:
[run 32392414122](https://github.com/Ian-Tseng/audit-method-data-flow/actions/runs/32392414122)
passed the producer `main` commit through `github.workflow_sha`, which did not
match the policy's central pin, so intake exited with no candidate or outbound
mutation. This observation is a regression fixture, not evidence that a later
dry run or live repair succeeded.

## Normal attempt

The workflow binds a canonical authorization manifest, uploads it as a
one-day artifact, and writes its SHA-256 identity to the run summary. After the
first environment approval it refetches the live repository, issue, label set,
default-branch commit, policy, and workflow pin. The agent runs without a
repository write token. A root-owned collector installed before the model
accepts only bounded UTF-8 additions/modifications inside the closed allowlist.

A fresh checkout applies the exact patch and runs one named validation profile
with no secrets and a denied network namespace where the runner supports it.
The second environment approval precedes all repository writes. Publication
uses the authorization-derived branch, never force-pushes, and reconciles an
existing branch, draft PR, and issue comment before retrying.

Human review still owns component-map acceptance, merge, version/release gates,
public publication, consumer update, and fresh-host activation.

## Emergency disable and rollback

Immediately remove the trigger label and lock both environments. Then preview a
caller-owned disable:

```powershell
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py --format json disable --repo-root "<producer-checkout>"
```

After review, repeat with `--apply` and commit the policy change. Run
`rollback-plan` to prepare a human-reviewed change that moves the caller and
policy together to the last compatible full SHA. A central denylist is only an
advisory doctor signal; a compromised pinned workflow cannot safely revoke
itself.

Never retry a timed-out publication blindly. Use the authorization ID and the
hosted run’s reconciliation result to classify the branch, tree, PR, and issue
comment as confirmed, missing, conflicting, or unknown.
