# Validation authority

The validation tree separates current structural authority from immutable
historical evidence.

- `component-map/accepted-map.json` is the only accepted component-to-element
  map. Candidates, deltas, observations, and scan-history events do not replace
  it until an explicit successful `accept` event names the candidate.
- `history/` contains append-only scan records. A schema-v2 evidence-bound JSON
  record is semantic audit authority for its own claims only while its stored
  integrity, skill, map, and cited evidence identities verify. Newer records do
  not silently supersede records with different objectives or scope.
- `reports/` contains deterministic Markdown views derived from v2 JSON. A
  report is never authority when its source JSON is missing or `verify` reports
  `REPORT_OUT_OF_DATE`.
- Schema-v1 records remain readable historical evidence but are
  `legacy_unbound`: their prose does not establish exact claim-to-evidence
  support and is never promoted automatically.
- `self-scan-input.json` is the retained v0.1.0 input fixture.
- `self-scan-input-v020.json` is the retained v0.2.0 input fixture.
- `problem-reporting-scan-input-v051.json` is the retained v0.5.1 reporting,
  issue-to-release, installed-update, and component-map synchronization input.
- Input fixtures are not current status authority. Report current status from
  the accepted map and the newest applicable verified v2 record, while naming
  scope, freshness, contradictions, limitations, and unresolved uncertainty.

No separate active project check table is currently designated for this
repository. If one is introduced, this file must name its exact path and
authority boundary before that table can participate in a status claim.

A newer scan does not erase an older failure. An accepted map describes what is
structurally addressable; it does not by itself prove a claim. A failed verify
never rewrites history: create a new record after refreshing the evidence.
