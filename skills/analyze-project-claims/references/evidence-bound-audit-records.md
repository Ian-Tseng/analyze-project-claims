# Evidence-bound audit records

Use scan-record v2 when a formal audit must show which exact artifact supports,
contradicts, limits, or contextualizes each material claim. Ordinary audits can
still stop at the agent's evidence table.

An evidence-bound record verifies structure, artifact identity, locators, and
freshness. It does not prove that evidence semantically entails a claim. Keep
the claim status and rationale as an explicit human or audited judgment.

## Authority model

- The accepted component map is the structural authority.
- A v2 record is semantic audit authority for its declared claims only while its
  canonical integrity, skill, map, schema, renderer, and evidence identities verify.
- The Markdown report is a deterministic, derived view of the JSON record.
- Historical v1 records remain immutable and render as
  `LEGACY_RECORD_UNBOUND`.

V2 claims reference one accepted `{component_id, element_id}` pair. Claims do
not alter the component map or its engine digest.

## Fast path

Run from the project being audited. Replace the skill path when it is installed
elsewhere.

```powershell
$Recorder = ".\skills\analyze-project-claims\scripts\record_scan.py"

py -3 $Recorder preflight `
  --map-root .\validation\component-map `
  --project-root .

py -3 $Recorder init `
  --map-root .\validation\component-map `
  --project-root . `
  --output .\scan-record.v2.json

py -3 $Recorder evidence digest `
  --source results\run.json `
  --locator "json-pointer:/metrics/accuracy" `
  --project-root . `
  --id evidence:run-accuracy

py -3 $Recorder validate `
  --record .\scan-record.v2.json `
  --map-root .\validation\component-map `
  --project-root .

py -3 $Recorder append `
  --record .\scan-record.v2.json `
  --map-root .\validation\component-map `
  --project-root . `
  --log-dir .\validation\history `
  --report-dir .\validation\reports
```

`validate` checks the closed input contract, accepted-map identity, references,
roles, and status combinations. `append` additionally reads local artifacts,
resolves locators, computes identities, enforces freshness-dependent rules, and
commits a new append-only record.

## Claims and bindings

Use stable lowercase IDs. A material claim has an exact statement, accepted-map
element reference, status, and semantic rationale.

Binding roles have distinct meanings:

- `supports`: evidence directly supports the scoped claim;
- `contradicts`: same-scope evidence conflicts with it;
- `limits`: evidence establishes a material boundary;
- `context`: useful background that never counts as support.

`not_tested` evidence is context-only. It cannot be bound as support,
contradiction, or limitation. Other declared methods may participate in those
roles, subject to the status, receipt, freshness, and human-review rules below.

The recorder enforces these structural rules:

- `supported` and `partially_supported` require current support;
- `partially_supported` requires an explicit limitation;
- `contradicted` requires counterevidence;
- `untested`, `invalidly_specified`, and `not_applicable` cannot carry support
  or contradiction bindings;
- a supported claim cannot hide unresolved contradiction;
- every evidence-backed limitation matches an explicit `limits` edge;
- the strongest safe claim must be material, resolve to an eligible claim, and
  have boundary IDs that exactly match its declared limitations;
- use `no_supported_claim: true` with a null strongest claim only when no
  supported or partially supported claim exists.

These checks prevent structurally unbound claims. They do not decide whether
the cited evidence is scientifically sufficient.

## Evidence identity

Local evidence uses a project-root-relative POSIX path. The recorder reads each
distinct file once and stores:

- file SHA-256, media type, and byte size;
- a typed locator;
- SHA-256 of the selected content;
- a deterministic evidence identity digest;
- bounded observation text and freshness state.

Supported locator forms are:

- `whole_file`;
- `json_pointer` with an RFC 6901-shaped value;
- inclusive one-based `line_range`;
- `artifact_key` for one top-level JSON key;
- `test_case` for an exact identifier in a persisted UTF-8 execution receipt.

For claims that a test ran or passed, cite a persisted result or execution
receipt. Test source code can be `context`; it is not evidence of execution.

Paths that are absolute, contain traversal or backslashes, escape the project
root, cross symlinks/junctions/reparse points, name a directory, or exceed the
source limit fail closed. Represent a directory through an explicit bounded
manifest or receipt file. A Git LFS pointer is a named unavailable state, not
the bytes of its referenced artifact.

External HTTPS evidence is never fetched implicitly. A supplied SHA-256 digest
or a full lowercase 40- or 64-hexadecimal object ID is recorded as
`declared_immutable`; labels such as `main`, `latest`, and version-like tags are
`unverifiable` without the digest. Query strings, fragments, and embedded credentials are
rejected. Unsafe Unicode controls and secret-like observations are also
rejected before persistence. An unverifiable support, contradiction, or
limitation blocks the strongest safe claim.

## Integrity identities

The canonical record digest covers the normalized payload plus output-schema,
recorder, and renderer identities; it excludes only its own
`canonical_payload_sha256` field. `output_schema_sha256` binds the persisted
contract. `renderer_sha256` and `recorder_sha256` both bind the exact recorder
module bytes, while `renderer_id` names the deterministic Markdown contract.
A digest confirms byte identity, not authorship or semantic truth. Unsalted
hashes of low-entropy selected values may be guessable, so reports do not expose
the selected bytes by default.

## Render and reverify

```powershell
py -3 $Recorder render `
  --record .\validation\history\<scan-id>.json `
  --output .\validation\reports\<scan-id>.md `
  --project-root .

py -3 $Recorder verify `
  --record .\validation\history\<scan-id>.json `
  --map-root .\validation\component-map `
  --project-root . `
  --report .\validation\reports\<scan-id>.md `
  --format json
```

`render` emits the same bytes for the same record and report location. It
refuses active schema, recorder, or renderer identity drift before emitting a
v2 view. Reports include the record digest, claim IDs, roles, links, locators,
external revisions, artifact and selection digests, freshness,
counterevidence, limitations, and the semantic-review boundary.

`verify` never rewrites history. It compares the record with the active skill,
full embedded-engine identity, recorder version, accepted map identity and
path, local artifact bytes and derived metadata, selected bytes, and optional
rendered report. After evidence changes, review the new state and
append a new record.

## Legacy migration

The flag-only command remains the v1 writer for one compatibility window:

```powershell
py -3 $Recorder --record .\legacy-input.json --log-dir .\validation\history
```

Render or verify a v1 record to see `LEGACY_RECORD_UNBOUND`. Create a draft
without inventing support:

```powershell
py -3 $Recorder draft-v2 `
  --legacy-record .\validation\history\<legacy>.json `
  --map-root .\validation\component-map `
  --project-root . `
  --output .\scan-record.v2.draft.json
```

The draft copies claim prose as `untested`, creates no evidence or bindings,
and selects no strongest claim. A reviewer must complete it.

Recorder 2.1.0 finalized the v2 implementation-identity contract. An intact
pre-release recorder 2.0.0 record that lacks `recorder_sha256` is reported as
`LEGACY_V2_CONTRACT_UNBOUND`; it is historical evidence, not a current verified
record. Recreate it from current evidence under recorder 2.1.0 or newer rather
than silently upgrading its claims.

## Error contract

Every failure prints a stable code plus the problem, cause, effect, fix, exact
retry guidance, and this reference URL. Important codes follow.

### record-schema-unsupported

The JSON shape or version is not part of the closed v2 contract. Start from the
v2 template and remove unknown fields.

### map-not-accepted

No ordinary accepted map exists under the declared project root. Reconcile and
explicitly accept a candidate first.

### map-identity-mismatch

The map integrity, current skill hash, map ID, or stored map digest differs.
Reconcile and explicitly accept the current structural map.

### claim-element-unknown

A claim references a component/element pair not present in the accepted map.
Use `preflight` to list eligible pairs.

### binding-missing

A claim status requires support, contradiction, or a limitation that is not
bound. Add the required relationship or lower the status.

### evidence-path-unsafe

A local source is missing, escapes the project root, crosses a reparse point,
or is not an ordinary file. Use a safe relative file or bounded receipt.

### evidence-locator-unsupported

The locator kind or shape is not supported. Use a documented typed locator.

### evidence-locator-missing

The locator no longer resolves in the current bytes. Correct it and append a
new record after review.

### evidence-digest-mismatch

The current artifact or selected bytes differ from the persisted identity.
Review the change; never rewrite the old record.

### external-evidence-unverifiable

An external reference has no locally recomputable or declared immutable
identity. Pin a SHA-256 digest or full 40-/64-hexadecimal object ID, or treat it only as context.

### executed-test-receipt-required

`executed_test` points at test source code rather than a persisted result, log,
or receipt. Use `inspected` with a context binding for source; cite run output
for execution evidence.

### sensitive-observation-rejected

An observation summary resembles a credential or private key. Redact it before
retrying. The rejected value is not printed by the error.

### verify-context-required

A v2 verify omitted the accepted map or project root. Provide both so the
command can recompute current identities instead of overstating verification.

### record-integrity-mismatch

The stored canonical payload no longer matches its integrity digest. Do not
trust or silently repair that record; restore the original or append a new
validated record.

### evidence-source-unavailable

The path is an unresolved Git LFS pointer or another named non-artifact state.
Materialize the artifact or cite a bounded receipt.

### record-text-unsafe

A value contains terminal, bidi, surrogate, invisible format, or other unsafe
control characters, or exceeds its bound. Replace it with bounded plain text.

### external-evidence-unsafe

An external reference is not safe query-free, fragment-free HTTPS. Remove
credentials, queries, fragments, or unsupported schemes.

### schema-identity-mismatch / renderer-identity-mismatch / recorder-identity-mismatch

The active output schema, deterministic renderer, or recorder implementation
differs from the one bound into the record. Use the matching released package
to reproduce the old view, or append a newly reviewed record under the current
contract.

### record-schema-unsupported / record-derivation-mismatch

A persisted v2 record is structurally invalid or its claim/evidence identities,
invariants, or derived summary do not replay exactly. A recomputed canonical
digest does not override this check. Restore the append output or append a new
record.

### evidence-method-role-conflict

A `not_tested` item was used as support, contradiction, or limitation. Keep it
as context or cite evidence collected with an applicable method.

### report-context-required

Writing a v2 report omitted `--project-root`, so local evidence links could not
be made relative to the output file. Supply the project root used at append.

### legacy-v2-contract-unbound

An intact pre-release recorder 2.0.0 record lacks the final code-bound recorder
identity. Preserve it as historical evidence; use the matching old package for
inspection or append a newly reviewed recorder 2.1.0 record.
### strongest-claim-unbound

The selected strongest claim lacks eligible current support, hides a
contradiction or limitation, or conflicts with the no-supported sentinel.

### legacy-record-unbound

The record predates v2. It remains readable, but no hashes or support roles are
inferred.

### report-out-of-date

The provided Markdown bytes do not match deterministic rendering of the JSON
record. Regenerate the derived report.

### record-commit-failed

An append-only target already exists or could not be committed. No existing
record is intentionally overwritten.

### report-write-failed

The JSON record committed successfully but report generation failed. Run the
printed `render` recovery command.

### record-io-error

A filesystem operation failed. Correct paths or permissions and retry; inspect
the printed effect before assuming any output exists.
