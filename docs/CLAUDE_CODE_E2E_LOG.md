# Claude Code End-to-End Evidence Log

## v0.7.0 public distribution result

**PARTIAL PASS - DISTRIBUTION E2E PASSED; RUNTIME NOT OBSERVED.** On
2026-08-15 (Asia/Taipei), the immutable public v0.7.0 release completed an
isolated user-scope install, registry listing, package verification, and
neutral-directory update dry-run for both Claude Code and Codex targets.
Claude client discovery and invocation were not run because this machine had
no `claude` executable. The isolated Codex home was not authenticated, so it
also was not used as substitute runtime evidence.

### Environment and release identity

| Field | Observed value |
| --- | --- |
| Operating system | Microsoft Windows NT 10.0.26200.0, x64 |
| GitHub CLI | 2.97.0 (2026-07-31) |
| Public source | `https://github.com/Ian-Tseng/analyze-project-claims` |
| Release | `v0.7.0` |
| Release commit | `347b5a82b653771cce75e98b7803c23d6bec6fbb` |
| Release state | GitHub immutable; `gh release verify v0.7.0` passed |
| Tag protection | Active update-and-deletion rules for `refs/tags/v*`; no bypass actor |
| Main CI | Six passing jobs: Windows, macOS, and Ubuntu on Python 3.10 and 3.12 |
| Requested agents | `claude-code` and `codex` |
| Scope and pin | user, unpinned |
| Claude path | `<isolated-home>\.claude\skills\analyze-project-claims` |
| Codex path | `<isolated-home>\.codex\skills\analyze-project-claims` |
| Package digest | `9d486dacb7d740e71e17c45f0a7243e7ca3f0f161382d8131afc129bcde95186` |

The smoke root set `USERPROFILE`, `HOME`, `HOMEDRIVE`, and `HOMEPATH` to one
disposable directory. Before installation, both target-specific user lists
were empty. After installation, each list contained exactly one canonical
v0.7.0 entry at its target path.

### Observed gates

| Gate | Status | Direct observation |
| --- | --- | --- |
| Public package preview | PASS | GitHub CLI fetched and rendered the canonical public source. |
| Empty isolated registries | PASS | Both target-specific user lists returned no installations before the smoke. |
| Claude-targeted install | PASS | One canonical v0.7.0 user-scope, unpinned entry appeared under `.claude/skills`. |
| Codex-targeted control install | PASS | One canonical v0.7.0 user-scope, unpinned entry appeared under `.codex/skills`. |
| Installed package integrity | PASS | Both installed copies returned `PACKAGE_VERIFIED` with the digest above. |
| Update rediscovery | PASS | A neutral-directory `gh skill update analyze-project-claims --dry-run` returned `All skills are up to date.` |
| Claude client discovery | NOT OBSERVED | No `claude` executable was available on this machine. |
| Real Claude invocation | NOT OBSERVED | `/analyze-project-claims` was not run. |
| Isolated Codex invocation | NOT OBSERVED | The isolated `CODEX_HOME` reported `Not logged in`. |
| Live replacement | NOT OBSERVED | An up-to-date dry-run does not install a later version. |

The release identity is supported by [GitHub release
v0.7.0](https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.0),
the six-job [main CI
run](https://github.com/Ian-Tseng/analyze-project-claims/actions/runs/31817785877),
the package
[manifest](../skills/analyze-project-claims/references/package-manifest.json),
the formal validation
[record](../validation/history/20260814T155937638082Z-c36faabe.json), and its
derived human-readable
[report](../validation/reports/20260814T155937638082Z-c36faabe.md).

### Complete the runtime gate on another PC

Run these commands in a clean user environment on the machine that has an
authenticated Claude Code installation:

```powershell
gh skill install Ian-Tseng/analyze-project-claims `
  skills/analyze-project-claims/SKILL.md `
  --agent claude-code `
  --scope user

gh skill list --agent claude-code --scope user `
  --json skillName,sourceURL,scope,version,pinned,path

gh skill update analyze-project-claims --dry-run
claude --version
claude
```

In the fresh Claude Code session, run `/skills`, confirm the exact
`analyze-project-claims` name, then invoke `/analyze-project-claims` on a
disposable non-sensitive fixture. Append the Claude version, operating system,
command, bounded output, and exit result here. Do not rewrite this observation.
A live replacement still requires a later immutable release and a separate
before/after invocation test.

## Historical v0.6.2 result

## Result

**PARTIAL PASS - RUNTIME NOT OBSERVED.** On 2026-08-13, the public v0.6.2
package completed a Claude Code-targeted managed install, registry listing,
manifest verification, and update dry-run in an isolated Windows user home.
Claude client discovery, invocation, and live replacement were not run because
this machine had no Claude CLI or Claude authentication.

This is distribution and update-rediscovery evidence, not full Claude runtime
E2E evidence.

## Environment and identity

| Field | Observed value |
| --- | --- |
| Operating system | Windows |
| GitHub CLI | 2.97.0 (2026-07-31) |
| Public source | `Ian-Tseng/analyze-project-claims` |
| Installed release | `v0.6.2` |
| Release tree | `b660e74053a2b7a188319faa3ecce8e5aacc2be7` |
| Requested agent | `claude-code` |
| Scope and pin | user, unpinned |
| Installed path | isolated `%TEMP%` user home under `.claude/skills/analyze-project-claims` |
| Package digest | `7ceed9ccd383001ca687f3c2a47f0414244f2b3dcef72e371eccdca7aab63d6f` |

The isolated home was removed after the run. The real user `.claude` directory
was not modified.

## Observed sequence

From a neutral consumer directory with isolated `HOME` and `USERPROFILE`:

1. `gh skill install Ian-Tseng/analyze-project-claims skills/analyze-project-claims/SKILL.md --agent claude-code --scope user` succeeded.
2. `gh skill list --agent claude-code --scope user --json skillName,sourceURL,scope,version,pinned,path` returned exactly one canonical user installation at the Claude-specific path, version `v0.6.2`, unpinned.
3. The installed package's `update_policy.py verify-package` returned `PACKAGE_VERIFIED` with the digest above.
4. `gh skill update analyze-project-claims --dry-run` rediscovered the install and reported that all skills were up to date.

| Gate | Status | Evidence boundary |
| --- | --- | --- |
| Portable metadata | PASS | Static compatibility only. |
| Public Claude-targeted install | PASS | Proves GitHub CLI distribution to the Claude path. |
| Registry identity | PASS | Proves source, version, scope, pin, and path metadata. |
| Installed payload integrity | PASS | Proves manifest-declared bytes. |
| Update rediscovery | PASS | Dry-run only; no replacement occurred. |
| Claude client discovery | NOT OBSERVED | `/skills` was not run. |
| Real Claude invocation | NOT OBSERVED | `/analyze-project-claims` was not run. |
| Live replacement | NOT OBSERVED | Requires authenticated runtime and a later release candidate. |

## Publisher-directory diagnostic

An earlier dry-run launched inside the publisher checkout found the valid user
installation but also warned that the checkout's project copy lacked GitHub
metadata. Repeating the same test from a neutral consumer directory removed the
warning and returned a single clean result. This confirms that update tests
must isolate consumer state from a publisher checkout; the first warning was
not a defect in the installed package.

## Remaining runtime gate

At the time of the run, `claude` was absent from `PATH`, the Claude credentials
file was absent, and `ANTHROPIC_API_KEY` was not set. To close the gate on an
authorized machine:

1. record the Claude Code version and start a clean authenticated session;
2. run `/skills` and capture discovery of `analyze-project-claims`;
3. invoke `/analyze-project-claims` on a disposable fixture and record the
   bounded result;
4. when a later immutable release exists, test replacement and prove only the
   next invocation loads it;
5. append those observations here without rewriting this historical result.

Until then, the safe claim is: managed Claude-targeted distribution and update
rediscovery passed on the recorded environment; Claude runtime behavior remains
unverified.

See [How to Validate a GitHub Skill Across Codex and Claude Code](MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md)
for the reusable procedure and evidence vocabulary.
