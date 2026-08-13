# Validation authority

The validation tree separates current structural authority from immutable
historical evidence.

- `component-map/accepted-map.json` is the only accepted component-to-element
  map. Candidate and delta files are proposals or observations until an
  explicit successful `accept` event names them.
- `component-map/scan-history/` and `history/` are append-only evidence.
  Never rewrite an earlier event or scan record.
- `self-scan-input.json` is the retained v0.1.0 input fixture.
- `self-scan-input-v020.json` is the retained v0.2.0 input fixture.
- `problem-reporting-scan-input-v051.json` is the retained v0.5.1 reporting,
  issue-to-release, installed-update, and component-map synchronization input.
- These input fixtures are not current status authority. Use the accepted map
  and the newest applicable immutable scan record together when reporting
  current status.

No separate active project check table is currently designated for this
repository. If one is introduced, this file must name its exact path and
authority boundary before that table can participate in a status claim.

A newer scan does not erase an older failure. A candidate that was not
explicitly accepted does not replace the accepted map.
