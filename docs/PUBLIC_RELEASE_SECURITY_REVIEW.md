# Public Release Security Review

## Executive summary

The 2026-08-13 review found no live credential or private machine-path material
in reachable source history. Publication remains conditional on an explicit
owner decision about the legacy commit-author email and successful validation
of v0.6.0. Repository visibility must remain private until those gates pass.

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

Status: owner decision required. Future commits use the GitHub no-reply
identity. Rewriting existing commits would replace published commit and tag
identities, invalidating the recorded release evidence; preserving history
accepts the email exposure.

## Medium priority

### PUB-003: Private vulnerability reporting requires public visibility

Status: staged. `SECURITY.md` directs reporters to GitHub private vulnerability
reporting. The owner must enable that repository feature immediately after the
visibility switch and verify that the **Report a vulnerability** action is
available.

## Passed checks

- Ten reachable commits were scanned for common GitHub, AWS, Slack, OpenAI,
  PyPI, private-key, and credential-bearing URL patterns.
- Six matches were intentional fake GitHub tokens in redaction regression
  tests; three path matches were synthetic `/home/person/...` test strings.
- The only collaborator is the repository owner.
- The one closed issue contains a bounded synthetic E2E report and no project
  content or credential.
- Four published releases contain no uploaded release assets.
- GitHub Actions has no retained workflow artifacts.
- The workflow passes no repository secrets to test steps.

## Limits

The history scan is deterministic pattern matching, not proof that no sensitive
semantic content exists. Actions hosted-runner logs and GitHub notification
delivery were not exhaustively reclassified. Public secret scanning and push
protection should be verified after publication.
