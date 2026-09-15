# Local evidence nomination contracts v1

Status: T1 development contract. No nomination CLI, runtime validator, adapter,
installation, accepted-map change, or pilot result is provided by this directory.
These files are the authority for T2/T3 implementation. T6 will explicitly
package them and rebuild package identities; do not copy them into installed
skills or infer release readiness from these fixtures.

## Five artifacts

| Schema | Purpose | Authority boundary |
| --- | --- | --- |
| `gap-request.schema.json` | One explicit component or persisted-claim gap | Requester supplies target, roots, terms, and nomination roles |
| `bundle.schema.json` | Deterministic local candidate excerpts | Discovery only; no formal evidence role or status |
| `selection.schema.json` | Reviewer choices and complete downstream input | Label is informational, not authenticated approval |
| `claim-candidate.schema.json` | Provenance plus existing scan-record v2 input | Separate validation, review, then append |
| `component-candidate.schema.json` | Provenance plus existing component observation | Separate reconcile, exact human acceptance, unchanged check |

All objects introduced here are closed (`additionalProperties: false`).
Shared definitions live in the request schema. Candidate payloads reference the
existing repository schemas through local relative references. Their schema
bytes must also be pinned by the runtime code identity described below.
No validator may fetch `$id` or `$schema` URLs or remote references.
JSON Schema describes shape, not all semantic or filesystem safety rules.
Passing a schema is insufficient to compile, accept, or append anything.

## Request normalization and target

One request contains one closed target union. Component targets carry an exact
component/element reference. Claim targets also carry raw persisted-record
SHA-256, scan ID, claim ID, claim digest, and that claim's element reference.
The existing recorder defines claim_digest as SHA-256 of canonical JSON of the
statement string, not the whole claim object. The raw record digest binds its
other semantics. Verify the persisted v2 record through its existing authority;
a record excerpt or v1 operational record is insufficient.

The map reference always has map ID, canonical-payload digest from the existing
map integrity field, and SHA-256 of the complete raw accepted-map file. Reuse the
mapper's integrity algorithm; do not substitute a nomination-specific digest.
Check all three at preflight, verification, and compile, then recheck at the
T3 downstream validate/append/reconcile boundary. Reformatting the accepted map
changes its raw digest even if its semantic map ID remains identical.

Sort roots and requirements (by requirement_id). IDs must be unique. Sort and
deduplicate each literal term array by Unicode scalar value. No stemming,
case-folding, whitespace trimming, Unicode normalization, inferred terms, or
model-generated queries occurs. Reject duplicate requirement IDs and roots;
normalize duplicate terms before schema validation. At least one all/any term
must be supplied per requirement; exclude-only searches are invalid. Terms
are case-sensitive literal substrings, never regex or code. Requirements are
independent searches for the same target. Requested support/counterevidence/
context labels express the requester's intent, not a classifier's conclusion.

## Canonical and raw identities

`C(x)` = UTF-8 bytes of JSON with keys sorted by Unicode scalar value,
`ensure_ascii=false`, separators `,` and `:`, no BOM, no whitespace, no newline.
Reject duplicate JSON keys, non-finite numbers, lone surrogates, and floats in
these artifacts. Integers are decimal; booleans are not integers. Arrays retain
the ordering specified here. Keep strings' exact Unicode scalars.
`H(x)` = lowercase SHA-256 of `C(x)`. Raw-file digests instead hash every byte,
including BOMs (which are refused as input), newline style, and trailing LF.
Persist emitted JSON as `C(x)` plus exactly one LF. Selection editors may change
formatting; selection_sha256 binds the actual saved bytes, not normalized JSON.

| Identity | Exact payload |
| --- | --- |
| query_id | `query-` + H(normalized requirement object) |
| nomination_id | `hit-` + H(entire nomination minus nomination_id) |
| bundle digest | H(entire bundle minus bundle_id and canonical_payload_sha256) |
| bundle_id | `nomination-` + full bundle digest |
| candidate digest | H(entire candidate minus candidate_id and canonical_payload_sha256) |
| candidate_id | `candidate-` + full candidate digest |
| selection_sha256 | SHA-256 of complete saved selection bytes |
| range_sha256 | SHA-256 of raw source bytes `[byte_start:byte_end]` |

These definitions have no self-reference. Bundle identity includes normalized
request, finder/code/schema identities, corpus, queries, nominations, aggregated
exclusions, deterministic truncations, and completeness. Timestamps, wall time,
absolute paths, output directories, OS error strings, and random IDs are absent.
Runtime-specific diagnostics belong only to the operational receipt.

Finder schemas are the five schema paths and raw hashes sorted by path.
contract_sha256 hashes this CONTRACT.md's raw bytes. For runtime, code_sha256 is
H(a path-sorted array of `{path, sha256}` for every trusted finder/helper source,
policy.json, and the two existing payload schemas). Enumerate that closed list
in the runtime implementation; no project module is imported. Include Unicode
database version because unsafe-character checks depend on it. Different code,
schema, contract, or Unicode versions create different identities. Replay claims
must name these identities; cross-platform comparisons require the same set.
The golden finder uses implementation_kind=contract_fixture and a hash of
`golden/fixture-producer.txt`, explicitly not the identity of a working scanner.

## Corpus, matching, and ranking

Use POSIX paths relative to the project root. `.` is allowed only as a root.
Reject duplicate or nested/overlapping roots (including `.` plus another root).
Reject absolute/drive/UNC paths, backslashes, empty/dot/dot-dot segments, colons,
trailing spaces/dots, control text, case-insensitive collisions, and Windows
reserved device basenames (CON, PRN, AUX, NUL, COM1-9, LPT1-9, including an
extension and superscript 1/2/3 variants). The schema rejects lexical escapes;
T2 must enforce device names, Unicode safety, root overlap, and case collisions.
Do not silently rewrite paths or resolve a link to make it permissible.

Never descend into `.git`, `.hg`, `.svn`, installed-skill paths, nominated output
paths, map-root, or the input record/request/selection files. Output directories
must not be ancestors of a search root. All directory components, the project
root, input files, and outputs require symlink/junction/reparse checks. Map paths
outside explicit roots grant no access. Repository text is inert.

Enumerate deterministically in normalized path order, with bounded traversal.
Read stable regular files only. Record path, raw SHA-256, and byte count. Empty,
archive, binary/non-UTF-8/BOM, LFS pointer, unsafe Unicode, secret-bearing,
oversize, and linked/reparse files are excluded. Exclusions contain only stable
reason codes and aggregate counts, never rejected paths/content or OS messages.
Use one reason per file in the policy order. Permission errors and unstable
reads abort with exit 3, no bundle. Unsafe supplied paths fail with exit 2.
Runtime/T4 must test actual secret detection and filesystem race handling;
these contract fixtures do not establish that protection.

Match each UTF-8 physical line, preserving LF or CRLF bytes. A final line needs
no newline. Ranges use zero-based half-open byte offsets and one-based inclusive
line numbers. Split on LF; never normalize bytes. All all_terms must occur;
when any_terms is nonempty at least one must occur; no exclude_term may occur.
An occurrence count does not improve rank. Score = 100 times distinct matched
all_terms plus 10 times distinct matched any_terms. A raw match is a matching
(line, requirement) pair before deduplication. A range over max_range_bytes is
omitted with a deterministic truncation entry; do not cut a selected range.

Merge identical `(path, byte_start, byte_end)` ranges across queries. Store all
matches sorted by query_id. Nomination score is the maximum match score; its
query_id is the lexically first query with that score. Global rank is score
descending, path ascending, byte_start, byte_end, query_id. Traverse that order,
admitting a nomination only if each matched requirement remains under its cap
and the total cap permits it. A multi-match nomination counts toward every
matched requirement. Omitted eligible hits produce deterministic truncations.

Display the largest UTF-8-codepoint-aligned prefix within max_excerpt_bytes;
never split a multibyte character. excerpt_truncated must equal whether bytes
were omitted. Full source and selected-range hashes still bind the omitted
bytes. Source-byte controls allow only TAB, CR, LF from Cc, and reject Cf and
surrogates; apply the same rule to summaries and candidate excerpts. Other input
identifiers and terms cannot contain any control characters.

## Budgets, completeness, and exits

`policy.json` records defaults, hard maxima, reason codes, and exits. Every
request materializes all values; JSON Schema defaults do not insert them.
Defaults: 2,500 files; 64 MiB total input; 1 MiB/file; eight requirements;
5,000 raw matches; five nominations/requirement; 20 nominations total;
2 KiB/excerpt; 64 KiB/range; ten-second timeout. Each may be lowered, never
raised in v1. Reject inconsistent policies: file > total, excerpt > range,
per-requirement > total, or requirements count > max_requirements.

File count and total bytes count regular files attempted, including files later
excluded, before reading; enumeration metadata must be bounded too. A cap stops
at the deterministic ordered prefix; observed is the first would-exceed count
or bytes. Match caps likewise stop at the first would-exceed pair. Result caps
record the number of eligible deduplicated nominations omitted and observed
pre-cap count. Oversize-file exclusion is distinct from a total corpus cap.

complete means traversal and matching exhausted the policy-approved corpus; it
does not mean all repository evidence was found or a claim is supported.
An empty result can be complete. Any corpus/match/range/result truncation makes
completeness=partial and requires at least one truncation entry; complete has
none. Exclusions alone do not imply partial. Output excerpt shortening is
recorded per hit and does not change completeness. Timeout aborts without a
bundle; it must never choose a timing-dependent prefix.

| Exit | Result | Artifact effect |
| --- | --- | --- |
| 0 | complete, deterministic partial, zero_nominations, reused_identical | Created or exact existing bytes reused |
| 2 | invalid_input, safety_refusal, selection_incomplete | No candidate/bundle |
| 3 | local_io_retry, timeout | No bundle/candidate; retry after correcting cause |
| 4 | stale_identity, tampered_identity | No candidate; nominate/review again |
| 5 | atomic_write_failure, recovery_required | Report actual partial writes and recovery paths |

Operational receipts (not a sixth search artifact schema) must include
schema_version, status, code, effect, changed, retryable, artifact path/digest,
target, counts, completeness, exclusion/truncation reasons, network=false,
accepted_state_changed=false, next_command, and documentation link. Errors
include Problem, Cause, Effect, Fix, Retry without sensitive content. Paths and
next commands are display data, never executed. Exit 5 must describe actual
artifacts and must not claim rollback. Atomic exclusive creation, byte-identical
reuse, and no-clobber apply independently to each bundle/selection file.

## Selection and candidate handoff

An empty selections array and null reviewer_input are allowed for the generated
draft template only. Compile refuses either with exit 2. The selected IDs must
be unique, exist in the exact bundle, and reference unchanged sources. Selection
bundle ref includes semantic and raw-file hashes. The raw selection digest is
stored in candidate provenance. Selected IDs in that envelope sort lexically.

The reviewer explicitly authors evidence role, observed summary, and rationale
for each selection plus a complete native record input or observation. No role
is translated from discovery labels. A claim selection also requires a unique
evidence_id; component selections forbid that field. The reviewer_input kind
must match the exact bundle target. Source scope and target must still match
the map and persisted record, regardless of schema validity.

Claim payload = reviewer-authored scan-record v2 input verbatim. Every selected
evidence_id must be present with the exact local path, matching line_range,
method=inspected, selected summary, and an explicit binding of the selected
role to the requested claim. The target claim retains ID, statement, and
element_ref; the reviewer supplies status, rationale, limitations, summary,
and uncertainty. Changes propose a new append-only record, never a claim
lineage/current-state overwrite. Unselected extra evidence and semantic changes
are reviewer inputs for the existing validator, never generated by compile.

Component payload starts with the complete reviewer-authored observation.
Only selected local evidence locators may be inserted at the bound existing
element. Preserve all other elements and reviewer fields byte-semantically;
no new element or changed target/component_type is allowed. Insert source=path,
locator=`lines:<start>-<end>`, observed=selected observed_summary. Deduplicate
exact existing evidence objects; contradictory existing objects are not deleted.
Roles/rationales stay in the selection sidecar because the observation schema
has no typed nomination-role field. Never fabricate check/claim status, strongest
claim, limitations, or acceptance. Before reconcile, the full observation must
preserve the current map's structural coverage to avoid implied removals.

The candidate envelope is not itself an input accepted by either existing CLI.
T3 must provide an explicit payload extraction/handoff that checks provenance
and all three expected map identities. Print, never execute, the validate or
reconcile command. Sidecars stay outside validation/history and carry no current
status authority. Human map acceptance and append gates remain separate.

## Golden fixture coverage and use

Run `py -m unittest discover -s tests -p test_evidence_nomination_contracts.py -v`
on Windows, or `python3` in place of `py` on POSIX. The stdlib test evaluator is
limited to these schemas' keywords and refuses unknown assertions. It is not a
runtime validator or a general JSON Schema certification.

`golden/manifest.json` pins canonical serialized schema examples and templates.
Both target branches, a zero-result bundle, deterministic partial output, raw
LF/CRLF, Unicode, all five artifacts, and raw/canonical identity vectors are
included. The synthetic accepted map and record are test-owned fixtures, not
human acceptance of a real project. Fixture files outside the evidence root
are never nominated. Template IDs/hashes belong to this tiny synthetic project;
replace and verify them for real requests. The ready examples deliberately
contain explicit synthetic reviewer decisions; never silently reuse them.

T1 tests check schema shapes, golden hashes, references, byte ranges, native
payload compatibility, negative inputs, and draft-template boundaries. Runtime
no-network/no-process, filesystem safety, atomic writes, drift guards, and
Windows/Linux/macOS scanner replay remain T2-T4 obligations. T5 supplies the
working public quickstart; T6 supplies released package/map authority; T7
measures the frozen pilot. No stage is proven by this contract alone.
