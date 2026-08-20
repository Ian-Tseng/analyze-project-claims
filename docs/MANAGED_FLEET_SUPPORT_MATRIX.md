# Managed Fleet Support Matrix

Status is bounded to repository candidates on 2026-08-20. `LOCAL_READY` is not
hosted activation.

| Repository | Planned version | Local updater/receipt | Managed caller | Repair activation | Canary order |
| --- | --- | --- | --- | --- | --- |
| `Ian-Tseng/audit-method-data-flow` | 0.1.1 | Implemented, evidence rebuild pending | Policy/caller onboarding in this release | Disabled until protected environments and live canary pass | 1 |
| `Ian-Tseng/audit-venue-submission` | 0.1.1 | Implemented, evidence rebuild pending | Policy/caller onboarding in this release | Disabled until protected environments and live canary pass | 2 |
| `Ian-Tseng/server-ops` | 0.1.2 | Implemented, evidence rebuild pending | Policy/caller onboarding in this release | Remains disabled until both earlier canaries pass | 3 |

Protocol v1 supports public GitHub Cloud repositories owned by `Ian-Tseng`, a
full 40-character analyzer workflow pin, Python `unittest` or `pytest` named
profiles, one canonical skill package root, exact owner triage, two protected
environments, and draft-only publication.

GitHub Enterprise Server, third-party owners, arbitrary validation commands,
automatic merge/release, automatic evidence acceptance, fleet-wide secrets,
force-push, remote production operations, and guaranteed invocation by every
agent host are unsupported.

Update this matrix only with exact observed evidence. Record local conformance,
hosted configuration, dry canary, agent run, validated draft, PR/main CI,
release, public install/update, and fresh activation as separate lifecycle
states.
