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
- provide the real author information in `CITATION.cff.template`;
- choose an author-approved software license and add `LICENSE`;
- rename the completed citation template to `CITATION.cff`;
- authenticate GitHub CLI;
- initialize the Git repository and review everything that will be committed.

Do not describe the repository as open source before a license has been
selected. A public GitHub repository without a license does not grant general
reuse rights.

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

Verify the owner in these files, and update it if the repository is transferred:

- `README.md`;
- `CITATION.cff.template`;
- `skill/analyze-project-claims/references/update-policy.schema.json`.

Complete the author and license fields in `CITATION.cff.template`, rename it to
`CITATION.cff`, and add the matching `LICENSE` file.

## 2. Rebuild and validate the package identity

Changing the schema owner changes the packaged bytes. Rebuild the package
manifest before committing:

```powershell
py -3 .\skill\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skill\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  build-manifest --write

py -3 .\skill\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skill\analyze-project-claims `
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

The installable source currently lives under `skill/`, so pass that directory
to GitHub CLI discovery:

```powershell
gh skill publish .\skill --dry-run
```

The final line should be:

```text
Dry run complete. Use without --dry-run to publish.
```

Review every warning even when the command exits successfully. Then publish the
tagged release exactly once:

```powershell
gh skill publish .\skill --tag "v$Version"
gh release view "v$Version"
```

Publishing creates a GitHub release. If post-publication evidence fails, do not
try to repair the same published tag. Fix the package, increment the version,
rerun validation, and publish a new candidate.

## 5. Test the public user journey

Use a clean environment with no duplicate `analyze-project-claims` install.
Preview the package before installing it:

```powershell
gh skill preview "$Owner/$Repository" `
  skill/analyze-project-claims/SKILL.md

gh skill install "$Owner/$Repository" `
  skill/analyze-project-claims/SKILL.md `
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

A real replacement test requires a later published candidate. During that
test, the current invocation must continue using its starting version and the
next invocation must load the verified new version.

## Evidence boundary

A successful dry-run proves package discovery and validation only. It does not
prove that the repository was pushed, that a release was published, that Codex
loaded it, or that automatic replacement works across supported operating
systems. Record those observations separately before claiming release
readiness.
