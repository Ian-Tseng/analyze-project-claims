# Changelog

All notable changes to this project are documented here.

## [0.8.2] - 2026-08-21

### Fixed

- Raise the bounded Codex `Stop` hook timeout from one to five seconds after
  a fresh Windows activation showed the host wrapper timing out even though
  the same no-op receipt completed locally in 251 ms.
- Preserve the hook's local-only, content-free, at-most-one-continuation, and
  no-outbound-action boundaries while adding a regression test for the exact
  deployed timeout.

## [0.8.1] - 2026-08-20

### Changed

- Route each consent-gated, enum-only skill-quality contribution to the
  originating `Ian-Tseng/<producer-repository>` instead of a fixed central
  issue tracker.
- Bind preview validation, GitHub visibility checks, issue creation, returned
  issue URLs, and owner intake to the same producer repository.
- Preserve local-only defaults, exact preview approval, separate public
  visibility confirmation, one-use replay protection, and post-create
  uncertainty handling.
- Give configuration-only managed-repair authorizations the same two-hour
  expiry field as live authorizations so hosted dry-run summaries complete.

## [0.8.0] - 2026-08-20

### Added

- A closed, content-free `SkillOutcomeReceipt` contract and portable CLI that
  validate compatible producer results and create deterministic local quality
  proposals.
- A private, bounded, atomic, replay-safe proposal store with concurrency,
  expiry, recursion, and hook-input guards.
- An optional repository-root Codex plugin with one bounded `Stop` adapter and
  a personal marketplace entry; explicit consumption remains the portable
  fallback.
- Exact, two-step, public-visibility-aware owner contributions that carry only
  enum and package identity fields, plus fail-closed maintainer intake.
- Read-only update-authority diagnostics for duplicate, manual, standalone,
  and plugin-managed installations.
- A reusable managed skill-quality guide and other-PC Claude validation
  checklist.
- One-use contribution delivery state, cross-process replay coverage, safe
  absolute GitHub CLI resolution, queue reclamation, and future-time rejection
  so the feedback loop remains bounded under failure and replay.

### Changed

- Component reconciliation now treats skill, mapper, scope, objective, and
  authority identity drift as promotable map drift.
- The embedded component-evidence engine is v1.3.0 and has a deterministic
  `build-self --write` release command.
- CI now requires formal accepted-map preflight; agent-maintainer candidates
  remain map-pending until exact owner reconciliation and acceptance.
- `SKILL.md` uses progressive disclosure while preserving the audit, formal
  evidence, lifecycle, reporting, analytics, update, and safety boundaries.
- `no_issue` remains a true no-op, active leases cannot be bypassed, expired
  receipts cannot starve newer work, dismissed proposals free bounded
  capacity, and consume reports its success state without overwriting it.

### Evidence boundary

- Local schemas, fixtures, replay/concurrency behavior, plugin structure, and
  plugin validation are tested. Live Codex continuation and Claude runtime
  invocation remain unobserved until their dated E2E logs say otherwise.

## [0.7.1] - 2026-08-15

### Changed

- Explicit `check-now` requests now honor existing automatic-update consent:
  `auto` performs immediate verified replacement, while all other modes remain
  read-only and preserve their stored policy.

## [0.7.0] - 2026-08-14

### Added

- Evidence-bound scan-record v2 with explicit claim, evidence, binding, limitation,
  accepted-map, and strongest-safe-claim identities.
- Append-only JSON records, deterministic Markdown reports, drift verification,
  legacy-v1 migration drafts, and stable recovery errors.
- Read-only lifecycle verification receipt interpretation with digest-bound,
  non-recursive follow-up requests.
- Cross-platform tests for adversarial record edits, mutable external references,
  symlink and Windows junction boundaries, report recovery, and code-identity drift.

### Changed

- Accepted component maps now receive their full authoritative schema and semantic-ID
  validation before a v2 record can bind to them.
- External revisions must be a full 40- or 64-hexadecimal object ID, or include an
  artifact SHA-256 digest, to count as declared immutable.
- Persisted v2 records replay their normalized invariants and derived identities;
  recomputing the outer checksum alone cannot make a malformed record valid.

[0.8.2]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.8.2
[0.8.1]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.8.1
[0.8.0]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.8.0
[0.7.1]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.1
[0.7.0]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.0
