# Managed Skill Fleet Quickstart

This quickstart joins one `Ian-Tseng` skill repository to the managed repair
protocol. The local milestone is `LOCAL_READY`: it proves the closed policy and
the exact SHA-pinned caller. It does not prove hosted environment protection,
agent execution, publication, release, installation, or fresh activation.

## Prerequisites

- A clean producer checkout whose package is at `skills/<skill-name>`.
- Python 3.10 or newer.
- The numeric GitHub repository ID from `gh api repos/Ian-Tseng/<repository> --jq .id`.
- A reviewed 40-character commit SHA from `Ian-Tseng/analyze-project-claims`
  containing `.github/workflows/managed-skill-repair.yml`.

From the analyzer checkout, preview exactly two producer files:

```powershell
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py --format json init `
  --repo-root "<producer-checkout>" `
  --repository Ian-Tseng/<repository> `
  --repository-id <numeric-id> `
  --skill <skill-name> `
  --package-root skills/<skill-name> `
  --workflow-sha <40-hex-sha> `
  --validation-profile python-unittest-package-v1
```

Replace every angle-bracket placeholder. Keep the checkout path quoted when it
contains spaces. Review the returned `files`, then repeat the command with
`--apply`. Enabling repair is a separate choice: add `--enable-repair` only
after both protected environments and the canary are ready.

Validate and inspect the local state:

```powershell
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py --format json validate --repo-root "<producer-checkout>"
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py --format json doctor --local --repo-root "<producer-checkout>"
py -3 .\skills\analyze-project-claims\scripts\managed_fleet.py --format json canary --dry-run --repo-root "<producer-checkout>"
```

Commit the policy and caller together. Provision `managed-repair-agent` and
`managed-repair-publish` with required reviewers, configure the repository
secret `OPENAI_API_KEY`, permit Actions-created pull requests, and run the
caller’s `workflow_dispatch` dry run. Follow
[Managed Fleet Operations](MANAGED_FLEET_OPERATIONS.md) for read-back and
rollback gates.

The reusable workflow is GitHub Cloud only in protocol v1 because its central
helpers use GitHub’s `$/path/to/action` resolution. GitHub Enterprise Server is
not a supported managed-repair host.
