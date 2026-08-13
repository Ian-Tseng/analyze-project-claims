# Publishing Analyze Project Claims

This guide is for maintainers preparing and publishing a public release. Run
commands from the repository root. The commands create external state only when
you run `gh repo create`, `git push`, or `gh skill publish` without
`--dry-run`.

GitHub CLI 2.90.0 or later is required. The `gh skill` commands are currently
in public preview.

## Release blockers

Resolve these before making the repository public:

- verify that the canonical GitHub owner remains `Ian-Tseng`;
- update every owner reference if the repository is transferred;
- verify the author identity and MIT license in `CITATION.cff` and `LICENSE`;
- scan current files and reachable history for credentials and private data;
- review commit identities, issues, releases, Actions logs, and artifacts;
- verify automatic reports require the private owner API;
- prepare `SECURITY.md` and enable private vulnerability reporting;
- verify the active `Protect version release tags` ruleset blocks update and
  deletion of `refs/tags/v*` with no bypass actor;
- either enable GitHub release immutability before publishing or describe the
  release guarantee as policy-only; GitHub does not apply this setting
  retroactively;
- authenticate GitHub CLI;
- review everything that will be committed.

Changing visibility exposes retained history to cloning and forking. Treat the
switch as a publication event, not a reversible privacy control.

## 1. Set the release identity

The canonical owner is currently `Ian-Tseng`. If the repository is transferred, set the new owner explicitly and rebuild the package manifest.

```powershell
$Owner = "Ian-Tseng"
$Repository = "analyze-project-claims"
$Version = (Get-Content -Raw .\VERSION).Trim()

gh auth login
gh auth status
```

Find the remaining release placeholders and verify owner references:

```powershell
rg -n "REPLACE_WITH_|github.com/Ian-Tseng|Ian-Tseng/analyze-project-claims" .
```

Verify the owner in `README.md`, `CITATION.cff`, and the packaged schemas. If
the repository is transferred, update those references and rebuild the package
manifest.

## 2. Rebuild and validate the package identity

Changing the schema owner changes the packaged bytes. Rebuild the package
manifest before committing:

```powershell
py -3 .\skills\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skills\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  build-manifest --write

py -3 .\skills\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skills\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  verify-package

py -3 -m unittest discover -s tests -v
```

On macOS or Linux, replace `py -3` with `python3`. Remove
`.release-doctor-state` after validation; it is local state and is ignored by
Git.

The expected results are:

- package verification succeeds;
- the complete test suite passes;
- `VERSION`, `CITATION.cff`, and `references/package-version.json` agree;
- no release placeholder remains;
- `git status` contains only intentional files.

## 3. Initialize and upload the repository

If this directory is not already a Git repository:

```powershell
git init
git branch -M main
git add .
git status
git commit -m "Release v$Version"
```

Inspect `git status` before committing. Do not upload caches, local policy
state, private evaluation snapshots, human annotations, credentials, or other
machine-specific artifacts.

Create and push the repository:

```powershell
gh repo create "$Owner/$Repository" `
  --public `
  --source . `
  --remote origin `
  --push `
  --description "Evidence-bounded project auditing for AI agents and research teams"
```

Use `--private` while release identity or licensing is incomplete. If the
remote repository already exists, add its canonical `origin` and use a normal,
reviewed `git push` instead of running `gh repo create` again.

## 4. Validate and publish the skill release

The installable source currently lives under `skills/`, so pass that directory
to GitHub CLI discovery:

```powershell
gh skill publish .\skills --dry-run
```

The final line should be:

```text
Dry run complete. Use without --dry-run to publish.
```

Review every warning even when the command exits successfully. Then publish the
tagged release exactly once:

```powershell
gh skill publish .\skills --tag "v$Version"
gh release view "v$Version"
```

Publishing creates a GitHub release. If post-publication evidence fails, do not
try to repair the same published tag. Fix the package, increment the version,
rerun validation, and publish a new candidate.

If **Enable release immutability** was turned on in repository Settings before
publication, verify the new release:

```powershell
gh release verify "v$Version"
```

Require that command to succeed before calling the release immutable. The
setting applies only to future releases. When enforcement is unavailable or
was enabled too late, use policy-only language: the maintainer does not move
published version tags, but GitHub has not made that release immutable.

The repository tag ruleset is a separate control: it prevents moving or
deleting `v*` refs, including existing tags, but it does not make release notes
or release assets immutable. A publication dry-run should no longer warn that
tag protection is absent.

## 5. Test the public user journey

Use a clean environment with no duplicate `analyze-project-claims` install.
Preview the package before installing it:

```powershell
gh skill preview "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md

gh skill install "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md `
  --agent codex `
  --scope user

gh skill list --agent codex --scope user `
  --json skillName,sourceURL,scope,version,pinned,path

gh skill update analyze-project-claims --dry-run
```

Confirm that the listing shows:

- the canonical GitHub repository;
- user scope;
- the published version;
- an unpinned installation;
- the expected Codex skill path.

Invoke the installed skill once. It should finish the substantive audit before
asking for update consent. Say `enable automatic updates`, invoke it again, and
confirm that an up-to-date check is silent.

Test Claude Code as a separate managed target in a clean environment with no
duplicate skill:

```powershell
gh skill install "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md `
  --agent claude-code `
  --scope user

gh skill list --agent claude-code --scope user `
  --json skillName,sourceURL,scope,version,pinned,path
```

From a neutral consumer directory outside the publisher repository, run `gh
skill update analyze-project-claims --dry-run`. Then start Claude Code, confirm
that `/skills` lists `analyze-project-claims`, and invoke
`/analyze-project-claims` on a disposable fixture. Record the Claude Code and
GitHub CLI versions, operating system, source version and tree, installed path,
manifest digest, invocation, and result. Test a manual directory copy
separately when needed; it is host-managed and does not establish managed
update state.

If no authenticated Claude Code CLI is available, restrict the release claim to
structural Agent Skills compatibility. Do not claim Claude Code runtime
validation until the smoke test above has been observed.

Use [How to Validate a GitHub Skill Across Codex and Claude Code](docs/MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md)
as the reusable procedure. Record exact observations and gaps in an evidence
log such as [Claude Code E2E Evidence Log](docs/CLAUDE_CODE_E2E_LOG.md).

A real replacement test requires a later published candidate. During that
test, the current invocation must continue using its starting version and the
next invocation must load the verified new version.

## 6. Verify problem-report operations

Run the reporter and owner-service tests before publishing:

```powershell
py -3 -m unittest discover -s tests -p "test_problem_report.py" -v
py -3 -m unittest discover -s tests -p "test_reporting_service.py" -v
```

For GitHub transport, verify visibility lookup fails closed. A public issue
must require both `--approved` and `--allow-public-issue` for the exact preview.
Verify new and legacy `auto-minimal` GitHub policies stop before delivery;
automatic reports require the private owner API. Security reports must use
private vulnerability reporting.

Configure the desired GitHub notifications. The Issues list or private API is
the authoritative receipt; a notification is convenience, not proof of
ingestion.

Triage the report before changing code. Eligible public reports can use the
owner-gated [Agent Maintainer](docs/AGENT_MAINTAINER.md) to produce an isolated,
validated draft pull request. Never execute issue text or automatically merge,
release, or close a report. Require a regression test, reviewed fix, passing
CI, and a new versioned SemVer release whose tag is not moved. Close the issue
only after the released fix and installed-update evidence exist.

If operating the optional API, follow
[Internal Problem Reporting](docs/PROBLEM_REPORTING.md). Production requires an
HTTPS reverse proxy, hashed scoped tokens, encrypted persistent storage,
backups, explicit retention, and owner monitoring. Test client isolation,
deduplication, triage status, deletion, and retention against the exact build.
The API service is owner infrastructure and is not installed with the skill.

Add report schemas and `problem_report.py` to the package-manifest check. Never
publish a package whose runtime event enum and JSON schema disagree.

If enabling the optional agent-maintainer workflow, follow
[Agent Maintainer for Internal Reports](docs/AGENT_MAINTAINER.md). Create the
owner-only `agent-ready` label and add dedicated `OPENAI_API_KEY` and narrowly
scoped, expiring `AGENT_MAINTAINER_TOKEN` secrets. Verify the exact pinned
Actions revisions before each release. Do not apply the label until the issue's
fixed disclosure and bounded form pass owner review. A successful run creates
only a draft candidate; it never replaces the release checklist above.

If operating installation analytics, follow
[Privacy-Bounded Installation Analytics](docs/INSTALLATION_ANALYTICS.md), run
both analytics test modules, publish the exact fields and retention policy, and
deploy the API behind HTTPS before distributing a scoped client credential.
Never describe repository traffic or the aggregate as downloads, users, or all
installs. If no production endpoint was observed, keep the feature described as
an inactive reference architecture.

## 7. Evidence boundary

A successful dry-run proves package discovery and validation only. It does not
prove that the repository was pushed, that a release was published, that Codex
or Claude Code loaded it, or that automatic replacement works across supported
operating systems. Record those observations separately before claiming
release readiness.
