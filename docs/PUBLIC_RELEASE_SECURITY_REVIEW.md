# Public Release Security Review

## Executive summary

The 2026-08-13 review found no live credential or private machine-path material
within the exact pre-publication scope recorded below. The owner accepted the
legacy commit-author email exposure, v0.6.0 passed validation, and the
repository was made public without rewriting the published history. The
post-public controls below were verified on the same date.

### Pre-publication history-scan scope

The deterministic history-pattern scan covered the first ten commits, ending
at `65b995c57ef6a3b395fd995686add21aeb29fd01`. The v0.6.0 publication commit
and later post-publication documentation commits were not reachable commits at
that scan boundary. Their passing CI and GitHub secret-scanning status are
separate evidence, not a retroactive expansion of the history scan.

## High priority

### PUB-001: GitHub reports could become public after a visibility change

Impact: a previously configured reporter could create an issue visible to
everyone after the destination repository becomes public.

Status: repaired in v0.6.0. GitHub delivery now verifies repository visibility,
fails closed when visibility is unknown, and requires both exact-report
approval and a dedicated `--allow-public-issue` flag for a public repository.
`auto-minimal` cannot supply that dedicated approval. The private owner API is
the appropriate automatic-reporting transport for a public product.

### PUB-002: Legacy commit identity contains a personal author email

Impact: making the repository public exposes the author email embedded in ten
existing commits.

Status: accepted by the owner. Future commits use the GitHub no-reply identity.
The published commit and tag identities were preserved, so the personal author
email remains visible in the ten historical commits.

## Medium priority

### PUB-003: Private vulnerability reporting requires public visibility

Status: enabled and API-verified after the public visibility switch.
`SECURITY.md` directs reporters to GitHub private vulnerability reporting.

## Publication postconditions

- GitHub reports the repository as public and private vulnerability reporting
  as enabled.
- An unauthenticated `git ls-remote` resolved `v0.6.0` to
  `7a2dd15d27c0776b2d4fca15fb79747076feb6c7`. `main` is expected to
  advance and is not part of this stable release-identity claim.
- `gh skill preview Ian-Tseng/analyze-project-claims
  skills/analyze-project-claims/SKILL.md` completed against the public source.
- A live bounded reporter test returned `PUBLIC_ISSUE_APPROVAL_REQUIRED` when
  given report approval without `--allow-public-issue`; the GitHub issue list
  remained unchanged.
- GitHub secret scanning and push protection are enabled.

## Passed checks

- The ten commits in the scope above were scanned for common GitHub, AWS,
  Slack, OpenAI, PyPI, private-key, and credential-bearing URL patterns.
- Six matches were intentional fake GitHub tokens in redaction regression
  tests; three path matches were synthetic `/home/person/...` test strings.
- The only collaborator is the repository owner.
- The one closed issue contains a bounded synthetic E2E report and no project
  content or credential.
- Every release through `v0.6.0` (five releases) contained no uploaded
  release assets when checked.
- GitHub Actions has no retained workflow artifacts.
- The workflow passes no repository secrets to test steps.

## Post-review hardening

Later on 2026-08-13, repository ruleset `20781141`, `Protect version release
tags`, was API-verified as active for `refs/tags/v*`. It blocks tag updates and
deletions, has no bypass actors, and reports that the current administrator can
never bypass it. This protects version-tag identity from that point forward.
It does not retroactively make the five release records through `v0.6.0`
immutable; GitHub continued to report `immutable=false` for those releases.

## Limits

The history scan is deterministic pattern matching, not proof that no sensitive
semantic content exists. Actions hosted-runner logs and GitHub notification
delivery were not exhaustively reclassified. No independent customer install
or production owner-API deployment was observed in this review.
