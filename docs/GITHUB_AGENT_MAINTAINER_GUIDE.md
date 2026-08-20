# Reusable GitHub Managed-Repair Guide

This is the public adoption guide for GitHub-managed `Ian-Tseng` skills. The
supported design is one central, full-commit-SHA-pinned reusable workflow plus
one closed policy and one thin caller in each producer repository.

Copying the legacy analyzer workflow, prompt, intake service, patch guard, or
collector into another repository is unsupported. Those files represent one
historical analyzer instance, not the reusable protocol. Central implementation
is resolved from the called workflow commit with GitHub Cloud’s
`$/path/to/action` syntax.

## Parameter sheet: what producers own

Each producer owns exactly:

- `.github/managed-skill-policy.json`, containing repository identity, package
  and allow/deny boundaries, version files, named validation profile, exact
  triager/label, fixed environments, draft-only publication, compatibility,
  enablement, and central workflow SHA;
- `.github/workflows/managed-skill-repair.yml`, a deterministic caller pinned to
  the same full SHA.

The policy is not executable configuration. Unknown keys, commands, dynamic
expressions, traversal, path collisions, third-party owners, weakened central
denials, arbitrary validation commands, non-draft publication, and non-SHA pins
fail closed.

Use [Managed Fleet Quickstart](MANAGED_FLEET_QUICKSTART.md) to preview and create
the two files. Use [Managed Fleet Operations](MANAGED_FLEET_OPERATIONS.md) to
provision and read back the two protected environments, repository secret,
Actions permissions, label, and dry canary.

## Keep four privilege zones

1. Intake checks the exact repository, owner-applied label, policy, base, issue
   identity, body digest, label-state digest, update time, workflow SHA, nonce,
   and expiry. A label is eligibility only.
2. Candidate preparation is gated by `managed-repair-agent`. The model gets no
   repository write token. The central collector is installed root-owned before
   the model and executes no candidate code.
3. Fresh validation applies the exact patch in a secret-free checkout, re-runs
   the central guard, uses a fixed named profile, and denies network while
   candidate code runs where the GitHub runner supports a network namespace.
4. Draft publication is independently gated by `managed-repair-publish`. It
   refetches live state, uses minimum caller-repository permissions, reconciles
   deterministic branch/PR/comment state, and never force-pushes or merges.

The caller passes only `OPENAI_API_KEY` explicitly. `secrets: inherit` and a
fleet-wide publisher token are forbidden. Prefer the caller’s `GITHUB_TOKEN`;
if a repository cannot grant the required draft-PR capability, stop and repair
the repository setting rather than broadening credentials.

## Lifecycle boundaries

The workflow may create a validated draft candidate. It cannot accept a
component map, rewrite historical evidence, merge, release, publish a skill,
update an installation, or prove fresh host activation. Owner review retains all
of those gates.

Users receive the substantive skill result first. Maintenance notices and one
content-free receipt may follow; model transcripts, project content, secrets,
and candidate patches are never automatic feedback payloads.

The local updater in each package remains separately consent-gated and verifies
one unambiguous native installation. The outcome receipt remains content-free
and local. Public issue creation remains a separately previewed and confirmed
action restricted to exact `Ian-Tseng` producer repositories.

## Cutover and rollback

Add all three callers in code, but canary in this order:

1. `audit-method-data-flow`
2. `audit-venue-submission`
3. `server-ops`

Keep `server-ops` disabled until the first two canaries pass. For a repository
with an old event workflow, disable the old trigger in the same reviewed commit
that enables the new caller; never permit both to respond to one label.

Emergency disablement is caller-owned: remove the label, lock both environments,
set policy `enabled` to false, revoke any repository secret if needed, and move
the caller/policy together to the last compatible reviewed SHA. A central
denylist is advisory because a bad pinned workflow cannot revoke itself.

For the complete issue-to-draft sequence, see
[Managed Repair Walkthrough](MANAGED_REPAIR_WALKTHROUGH.md). For multi-host
installation boundaries, see [Multi-Agent Install Topology](MULTI_AGENT_INSTALL_TOPOLOGY.md).
