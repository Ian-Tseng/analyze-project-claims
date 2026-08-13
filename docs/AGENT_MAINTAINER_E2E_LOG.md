# Agent-Maintainer Local E2E Log

Date: 2026-08-13 (Asia/Taipei)

Status: local contract and partial GitHub owner setup observed; hosted GitHub
execution not observed.

## Scope

This record covers the no-network agent-maintainer simulation, local
validation, and the separately observed owner-setup state described below. The
local simulation does not use an OpenAI API key. No run has invoked the Codex
GitHub Action, created or labeled a GitHub issue, published a candidate branch
or pull request, merged, released, updated an installed copy, or observed a
fresh installed activation.

Secret values were not printed, copied into the repository, or included in
test output. GitHub's secret-name inventory is evidence only that a named
secret exists; it does not reveal or prove the validity, scope, billing limits,
or runtime behavior of its value.

## GitHub owner setup observed

On 2026-08-13, authenticated GitHub CLI reads and writes established these
limited facts for `Ian-Tseng/analyze-project-claims`:

- an Actions secret named `OPENAI_API_KEY` exists;
- the owner-only `agent-ready` label exists with the documented description;
- Actions are enabled and all actions are allowed;
- the default workflow token permission is read-only and pull-request approval
  is disabled;
- no `AGENT_MAINTAINER_TOKEN` secret was present in the secret-name inventory.

The OpenAI key was copied to GitHub through standard input and its value was
not placed in a command argument or log. These observations do not establish
that the key is valid or that a hosted run succeeds. The separate publisher
token remains a required setup gate because it is intentionally unavailable to
the Codex job and is needed only after independent validation.

## System under test

```text
exact disclosed report -> owner and label intake -> minimized task
-> red regression -> guarded patch -> SHA-256-bound artifact
-> fresh checkout -> second trusted guard -> green regression
```

The implementation is
`tests/test_agent_maintainer.py::LocalPipelineE2ETests`.

## Observations

| Claim | Local observation | Limit |
|---|---|---|
| Exact intake | The report passes owner, repository, issue, label, title, body, disclosure, and event checks. | No live issue event was received. |
| Data minimization | The task omits raw issue text, reporter identity, and installation identity. | Provider infrastructure logs were not audited. |
| Regression first | The focused test is red before and green after the patch. | The fixture is synthetic. |
| Candidate bounds | The guard accepts the eligible text patch; separate tests reject forbidden surfaces. | Not proof against every hostile technique. |
| Patch identity | The same hashed bytes are applied to a fresh checkout. | No GitHub artifact transfer was exercised. |
| Independent validation | Guard and focused test run again in the fresh checkout. | Hosted validation was not invoked. |
| Publication boundary | Workflow tests allow only a new draft and exclude merge and release. | No branch or PR was created. |
| GitHub owner setup | `OPENAI_API_KEY` and `agent-ready` names were observed in repository settings. | Secret validity and all hosted jobs remain untested; the publisher token is absent. |

## Commands and final results

Commands were run from the repository root:

| Check | Command | Observed result |
|---|---|---|
| Agent-maintainer contracts and local chain | `py -3 -m unittest discover -s tests -p test_agent_maintainer.py -v` | 16 passed |
| Documentation/package contract | `py -3 -m unittest discover -s tests -p test_record_scan.py -v` | 5 passed |
| Full repository suite | `py -3 -m unittest discover -s tests -v` | 122 passed; 1 Windows privilege-dependent symlink test skipped |
| Package integrity | `py -3 skills\analyze-project-claims\scripts\update_policy.py --skill-root skills\analyze-project-claims --state-dir .release-doctor-state verify-package` | `PACKAGE_VERIFIED`; normalized GitHub CLI notice digest `ecc370aad9d55b6248b23b98b67255c62e86125b95d53c12f397a7281143c8e6` |
| Protected collector syntax | `bash -n maintainer_service/post_agent.sh` | Exit 0 |
| Workflow syntax | PyYAML safe-load of `.github/workflows/agent-maintainer.yml` | Passed |
| Diff whitespace | `git diff --check` | Exit 0; an existing CRLF-to-LF warning for `PUBLISHING.md` was non-failing |

An initial package-style unittest command executed no product tests because
`tests/` is not a Python package. The supported discovery commands above
were then used and passed.

The component-map observation was explicitly reconciled and accepted, followed
by a zero-change reconciliation. After this log changed, the same
accept-then-zero-change gate was run again. The authoritative current map and
append-only event trail live under `validation/component-map/`; its generated
ID is intentionally not copied into this source because the map hashes this
file and would otherwise become self-referential.

These results establish the local contract only. The hosted GitHub, provider,
draft-PR, release, installed-update, and fresh-activation states remain
unobserved.

## Reuse

Use [Reusable GitHub Agent-Maintainer Guide](GITHUB_AGENT_MAINTAINER_GUIDE.md)
for adaptation. Copy the evidence categories, not this repository's result.
