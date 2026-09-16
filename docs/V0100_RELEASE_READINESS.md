# v0.10.0 release preparation

Status: publication authorized; revised exact map acceptance remains pending.

The release candidate sets the citation date to 2026-09-16 and moves the accumulated
change descriptions into a dated v0.10.0 changelog entry. The README plugin pin
and publisher observation commands also target v0.10.0. No runtime, package,
contract, test or installed skill bytes are changed by this preparation.

## Source authority

The native candidate is `component-map-3df56ac1a6d5` with SHA-256
`c6d2068739baf776aa4129774eb28306b5be5f10ada760f0b64ff300477c38a4`. CHANGELOG.md, CITATION.cff, README.md and PUBLISHING.md source hashes differ; component
and element definitions are unchanged. The candidate is in the native candidates
directory. Human approval precedes acceptance and unchanged reconciliation.
The prior accepted map and formal history remain preserved.

## Validation observed

- Package manifest and embedded engine verification passed.
- Official skill and plugin validators passed.
- Offline quality-loop conformance produced QUALITY_PROPOSAL_READY, deduplicated
  replay and outbound NONE.
- The publication dry-run completed without warnings.
- GitHub release immutability is enabled. The active v* ruleset prevents updates
  and deletion and has no bypass actor.
- The unchanged runtime previously passed all six platform/Python cells on main
  commit `7e5b50609b9e946b808f4dae6a6bba079b317a72`. Final release-tree PR and
  main checks must pass after exact map acceptance.

## Remaining gates

Approve the exact map, reconcile unchanged, verify a fresh formal record, merge
and require CI on the resulting release commit. Publish v0.10.0 exactly once and
verify the immutable release. Publishing does not establish installed replacement,
client discovery or fresh activation.

T7 is deferred because human reviewers are unavailable. No human labels, timings,
review-time improvement or general reliability result is claimed. Four public
source candidates are retained locally for future preparation, outside this repo.

The earlier metadata-only proposal `component-map-0790d947d18d` remains preserved.
The release-instruction inventory found two more mapped source corrections; the
revised candidate requires exact approval. The authorized release notes are unchanged.
