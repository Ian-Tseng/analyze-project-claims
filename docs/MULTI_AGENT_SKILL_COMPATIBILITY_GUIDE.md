# How to Validate a GitHub Skill Across Codex and Claude Code

Use this procedure to make cross-agent compatibility claims that are portable,
repeatable, and no stronger than the collected evidence. A valid `SKILL.md` is
the start of the process, not proof that either client discovered or ran it.

## Evidence ladder

```text
format -> payload -> targeted install -> update rediscovery
       -> client discovery -> real invocation -> live replacement
```

| Gate | Required evidence | What it does not prove |
| --- | --- | --- |
| Format | `SKILL.md` uses the Agent Skills fields accepted by the target clients. | Package completeness or client behavior. |
| Package integrity | A clean, manifest-declared payload passes its verifier. | Installation or discovery. |
| Targeted install | The package installs with the intended agent and scope and appears in `gh skill list`. | That the client loaded it. |
| Update rediscovery | `gh skill update <name> --dry-run` finds the clean, unpinned install from a neutral directory. | Replacement or reload. |
| Client discovery | The target client's skill listing shows the installed name. | Successful execution. |
| Real invocation | A disposable fixture produces the expected bounded response. | Future-version replacement. |
| Live replacement | A later immutable version is installed and only the next invocation uses it. | Reliability on untested clients or operating systems. |

Treat each row as an independent release gate. Record an unobserved row as
unobserved rather than inferring it from an earlier pass.

## 1. Keep one portable package

Use the canonical layout:

```text
skills/<skill-name>/
  SKILL.md
  assets/
  references/
  scripts/
```

Keep top-level frontmatter within the Agent Skills specification. At minimum,
provide `name` and `description`; use only supported optional fields such as
`license`, `compatibility`, `metadata`, and `allowed-tools`. Put client-specific
installation instructions in repository documentation instead of creating
divergent package copies.

## 2. Verify a clean release payload

Build and verify the package manifest before publishing. If the working tree
contains unrelated files under the package root, do not delete or ignore them
to obtain a pass. Export the tracked release tree, overlay only the intended
changes, and verify that clean candidate instead.

For this repository:

```powershell
py -3 .\skills\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skills\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  verify-package
```

A manifest pass proves byte-level package integrity for that candidate. It does
not prove client compatibility.

## 3. Install once per target agent

Use an isolated user home with no duplicate installation. Preview the public
source, then install the same canonical package for each target:

On Windows, start a fresh PowerShell process and bind every home variable to
the same disposable root. Setting only `HOME` or only `USERPROFILE` is not a
complete isolation boundary for tools that consult Windows home semantics:

```powershell
$SmokeHome = Join-Path $env:TEMP "skill-smoke-$([guid]::NewGuid())"
New-Item -ItemType Directory -Force -Path $SmokeHome | Out-Null

$env:USERPROFILE = $SmokeHome
$env:HOME = $SmokeHome
$env:HOMEDRIVE = [IO.Path]::GetPathRoot($SmokeHome).TrimEnd('\')
$env:HOMEPATH = $SmokeHome.Substring($env:HOMEDRIVE.Length)

$BeforeCodex = gh skill list --agent codex --scope user --json skillName |
  ConvertFrom-Json
$BeforeClaude = gh skill list --agent claude-code --scope user --json skillName |
  ConvertFrom-Json

if ($BeforeCodex.Count -ne 0 -or $BeforeClaude.Count -ne 0) {
  throw "The disposable user-scope registries are not empty."
}
```

Keep that process isolated for the rest of the install, list, verification,
and update checks. Do not reuse the operator's normal shell, because changing
these variables can redirect unrelated user-scoped tools.

```powershell
gh skill install OWNER/REPOSITORY skills/SKILL_NAME/SKILL.md `
  --agent codex --scope user

gh skill install OWNER/REPOSITORY skills/SKILL_NAME/SKILL.md `
  --agent claude-code --scope user
```

Inspect the registry entry:

```powershell
gh skill list --agent claude-code --scope user `
  --json skillName,sourceURL,scope,version,pinned,path
```

Require the canonical source URL, expected version, user scope, unpinned state,
and the target agent's expected path. A direct copy into `.codex/skills` or
`.claude/skills` can test layout, but it is an unmanaged fallback and cannot
establish GitHub CLI update behavior.

## 4. Test update rediscovery from a neutral directory

Leave the publisher repository before testing updates:

```powershell
Set-Location $env:TEMP
gh skill update SKILL_NAME --dry-run
```

Running from the publisher repository can make its project copy look like a
second installation or produce a missing-metadata warning. A neutral consumer
directory separates the installed user skill from publisher checkout state.
Require a clean rediscovery result before advancing the evidence claim.

## 5. Observe each client

For Codex, list the installed skill and invoke it using the host's supported
skill syntax. For Claude Code:

1. Record `claude --version` and the operating system.
2. Start a clean session; restart if the personal skills directory was created
   after the earlier session started.
3. Run `/skills` and confirm the exact skill name.
4. Invoke `/SKILL_NAME` on a disposable, non-sensitive fixture.
5. Capture the command, bounded output, exit status, and unexpected behavior.

Client discovery and real invocation are separate observations. Never label a
metadata check or copied directory as runtime validation.

If the client executable is absent, record discovery and invocation as `NOT
OBSERVED`; do not substitute filesystem inspection. If the client is present
but the isolated home is not authenticated, record the same status and the
authentication boundary. Distribution evidence remains valid, but runtime
evidence has not advanced.

## 6. Validate replacement separately

A genuine managed-update test needs two published, immutable versions. Begin an
invocation on the older version, allow the updater to install the later clean
version, and verify that the running invocation retains its starting bytes.
Start a new invocation and prove that it loads the later version. Record both
version identities and package digests.

Do not move an existing version tag to make this test convenient. Publish a new
SemVer version and retain the earlier evidence.

## Evidence record

For every run, capture:

- date, operating system, target client, and client version;
- GitHub CLI version and authentication state without tokens;
- canonical repository, release tag, and Git tree identity;
- requested agent, scope, pin state, and resolved install path;
- package-manifest digest and verification result;
- update dry-run result from a neutral directory;
- client discovery, exact invocation, bounded result, and exit status;
- live replacement result, or an explicit reason it was not observed.

Use `PASS`, `FAIL`, `BLOCKED`, and `NOT OBSERVED` consistently. Keep commands and
relevant output, but never include credentials, private prompts, or project
data.

## Release language

State the highest completed gate and name the next missing gate. Examples:

- "Agent Skills metadata and clean package integrity passed. Runtime was not
  observed."
- "Claude-targeted install, registry listing, package verification, and update
  dry-run passed. Claude client discovery and invocation were not observed."
- "Live replacement passed on the recorded client and operating system; other
  hosts remain untested."

Compatibility evidence is versioned. Re-run affected gates when the package,
client, GitHub CLI, installation layout, or update contract changes.

## Operational completion rules

- Enable release immutability before publication and verify it afterward.
- Treat version-tag rules and release immutability as separate controls.
- If a merge command fails only while deleting a branch held by another local
  worktree, query the remote pull-request state before doing anything else. A
  remote `MERGED` result must not be retried.
- Retain an isolated smoke directory until source, scope, version, pin, path,
  manifest digest, and update output have been recorded.
- Keep earlier dated observations append-only. A newer release adds evidence;
  it does not retroactively strengthen an older run.

## References

- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [GitHub CLI `gh skill install`](https://cli.github.com/manual/gh_skill_install)
- [Safe managed-update design](MANAGED_SKILL_UPDATE_GUIDE.md)
- [Managed-update replacement evidence](MANAGED_UPDATE_E2E_LOG.md)
- [Current Claude Code evidence](CLAUDE_CODE_E2E_LOG.md)
