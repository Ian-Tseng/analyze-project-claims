# Changelog

All notable changes to this project are documented here.

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

[0.7.1]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.1
[0.7.0]: https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.0
