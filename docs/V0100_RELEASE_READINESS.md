# v0.10.0 release preparation

Status: prepared; exact release-map acceptance and publication remain pending.

The release candidate sets the citation date to 2026-09-16 and moves the accumulated
change descriptions into a dated v0.10.0 changelog entry. No runtime, package,
contract, test or installed skill bytes are changed by this preparation.

## Source authority

The native candidate is `component-map-0790d947d18d` with SHA-256
`c8fd3ce25f0b13882f921a32a2a615f4839aeced11f0134c55b808e8b7f0b68b`. Only CHANGELOG.md and CITATION.cff source hashes differ; component
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
