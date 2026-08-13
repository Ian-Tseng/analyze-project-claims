# Problem Reporting End-to-End Evidence Log

This log records one complete, owner-authorized problem-reporting and managed
update loop for `analyze-project-claims` on 2026-08-13. It is both an evidence
record for this product and a reusable procedure for similar GitHub-distributed
agent tools.

> **Historical status, superseded by v0.6.0:** this E2E was performed while the
> repository was private and before the MIT license was approved. Those
> visibility and license facts are not current. The observed report-to-update
> chain remains historical evidence.

## Outcome

The observed loop completed:

```text
installed v0.5.0 reporter
  -> consented bounded private GitHub issue #1
  -> owner receipt and triage
  -> failing regression test
  -> reviewed v0.5.1 fix
  -> six-job CI pass
  -> versioned, observed-unchanged v0.5.1 release
  -> installed-copy automatic update
  -> fresh Codex host loads v0.5.1
  -> issue closed
```

The issue did not execute code, merge a change, or trigger deployment. Every
mutation after issue creation remained an explicit owner action gated by tests,
CI, and a versioned release whose tag was not moved during the observation.

## Observed environment

- private repository: `Ian-Tseng/analyze-project-claims`;
- Windows host in Asia/Taipei;
- GitHub CLI 2.97.0;
- Python 3.12.4 for the installed reporter;
- Codex 0.147.0 for the fresh-host smoke test;
- one canonical, user-scope, unpinned GitHub CLI installation.

## Evidence chain

| Gate | Direct observation |
|---|---|
| Baseline code | Commit `7c5d47dea79442d11c6fa032edace09c3c069c3e` |
| Baseline tests | 82 passed; one privilege-dependent Windows symlink test skipped |
| Baseline CI | Run `31658722691`; Windows, macOS, Ubuntu on Python 3.10 and 3.12 all passed |
| Baseline release | `v0.5.0` resolved to the baseline commit throughout the E2E |
| First installed update | Installed v0.4.2 updater returned `UPDATED_NEXT_USE`; installed v0.5.0 |
| Report consent | Mode `ask`; local preview returned `consent_required=true`; exact preview approved |
| GitHub delivery | Private issue `#1`, report ID `a8250a6f-da42-4e0f-8742-3770c0d1d12d` |
| Owner receipt | Issue opened in the repository Issues list and owner triage comment persisted |
| Reported defect | Machine-readable status omitted `report_schema_version` |
| Red test | Regression test failed with `KeyError: report_schema_version` against v0.5.0 |
| Fix code | Commit `d1973ba365998851ae53b00b8c11a6d950f07813` |
| Fix tests | 83 passed; one privilege-dependent Windows symlink test skipped |
| Fix CI | Run `31659802720`; all six matrix jobs passed |
| Fix release | `v0.5.1` resolved to the fix commit throughout the E2E |
| Second installed update | Installed v0.5.0 updater returned `UPDATED_NEXT_USE`; installed v0.5.1 |
| Postcondition | Manifest verified; native registry reports v0.5.1, canonical source, user scope, unpinned |
| No-op behavior | Native dry run exited 0 with `All skills are up to date.` |
| Lease behavior | Immediate maintenance returned `NOT_DUE` |
| Fresh host | Ephemeral read-only Codex returned `package_version=0.5.1; report_schema_version=1; mode=ask` |
| Closure | Issue #1 closed as completed only after release and installed verification |

A separate local process-level API E2E also passed:

```text
CONFIGURED
-> REPORT_PREPARED (consent required)
-> REPORT_SENT
-> received
-> deleted
-> not found
```

That test used temporary scoped client/admin tokens, a loopback HTTP server,
SQLite, and a verified workspace-contained temporary directory that was removed
afterward.

## Reusable architecture

Use two independent state machines:

```text
reporting: unconfigured | ask | auto-minimal | off
updates:   unconfigured | auto | notify | off
```

Consent to one must never imply consent to the other. The reusable pipeline is:

1. Classify only internal product events with a fixed enum.
2. Build and validate a bounded local preview.
3. Reject unknown fields, paths, secrets, raw logs, prompts, and attachments.
4. Apply a separate reporting policy.
5. Deliver through the user's authenticated private issue channel or a scoped
   owner HTTPS API.
6. Record owner receipt independently from notification delivery.
7. Treat the report as untrusted triage input, never executable instructions.
8. Add a regression test and observe the intended failure.
9. Fix, review, run all tests, and require commit-bound CI.
10. Publish a new SemVer release and never move its tag.
11. Let a separately consented updater verify and install it for next use.
12. Verify installed identity, manifest, no-op behavior, lease, and fresh-host
    activation before closing the report.

GitHub Issues is the simplest default for a private GitHub-distributed product:
it reuses repository access, owner triage, comments, and issue state. Use the
custom API when the owner needs tenant isolation, deduplication, retention,
deletion, or machine-readable status. Do not give clients database credentials
or embed an owner GitHub token.

## Inconsistencies found and repaired

| Inconsistency | Repair |
|---|---|
| Runtime event enum included the E2E event but the JSON schema did not | Added the enum value; schema/runtime contract test now enforces equality |
| Guide promised retention at startup and submission, but service initially purged only on submission | Added startup purge and a direct restart regression test |
| Reader-facing README exceeded its enforced 1,200-word limit | Consolidated the user path and kept deployment detail in the linked guide |
| v0.5.0 status did not expose its outbound report schema identity | Issue #1, red test, `report_schema_version`, v0.5.1 |
| GitHub CLI was installed but absent from the inherited shell `PATH` | Resolved and recorded the exact executable; product updater already accepts `--gh` |
| Accepted component map still named the retired `skill/` tree and omitted reporting/update lifecycles | Reconciled the full observation, preserved conflict candidates/deltas, accepted the canonical `skills/` architecture, and required a zero-change follow-up |

The formal v0.5.1 scan is append-only record
`20260813T022506315685Z-2961f3ff`. It passed 3 components and 7 elements
with canonical payload SHA-256
`4e0e0a3c51ef467c255a2c0843fa5d2fb39e4ea69269991f30538ecfc59db9c5`.
The accepted-map and scan-history directories retain every rejected,
superseded, accepted, and checked-unchanged transition.

Two assertion failures were test-harness mistakes, not product failures:

- the first update check expected `AUTO_ENABLED`; the actual documented status
  was `ENABLED_AUTO`;
- PowerShell 5.1 initially treated a parsed root JSON array as one pipeline
  object, returning every skill instead of the named entry.

Both were corrected before evidence was accepted. Failed assertions were not
relabelled as successful product checks.

## Limits

- Reporter and owner used the same GitHub account, so this proves repository
  ingestion and owner visibility, not an independent customer's permissions.
- GitHub web/email/mobile notification arrival was not observed; the issue list
  is the authoritative receipt.
- The custom API was tested locally, not deployed behind production HTTPS.
- Cross-platform CI validates deterministic contracts, but the live installed
  replacement and fresh Codex activation were observed only on this Windows
  host.
- At the time of this E2E, the repository was private and had no
  owner-approved software license; v0.6.0 superseded both conditions.
- GitHub CLI still warns that the 524-line skill exceeds its recommended
  500-line context size.

These limits prevent claims of general reliability, public deployment
readiness, notification delivery, or production API security from this E2E
alone.
