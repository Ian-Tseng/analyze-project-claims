# Claude Code End-to-End Evidence Log

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
