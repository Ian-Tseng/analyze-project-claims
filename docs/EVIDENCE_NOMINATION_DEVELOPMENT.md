# Local evidence nomination development CLI

T1-T3 provide a repository-local, standard-library nomination CLI, reviewed
claim/component compilers, and guarded native handoffs. The search CLI lives in
`scripts/`; it is not installed or released. T3 also changes the development
package's native validator/recorder/reconciler and rebuilds their content
identities. T4's broader adversarial/platform audit, T5's public journey,
T6's release authority, and T7's pilot remain pending. Search results propose
excerpts; they do not establish claim status.

## Inputs and commands

Use an explicit [v1 gap request](../contracts/evidence-nomination/v1/CONTRACT.md).
Its map must be accepted by the existing workflow and match all three bound
identities. Claim targets also need their exact persisted v2 record. Supply all
resource-policy fields; no query terms, roles, or default budgets are inferred.
The synthetic [templates](../contracts/evidence-nomination/v1/templates/) are
examples tied to the fixture project, not live project approvals.

Run from this repository. Use `python3 -I` instead of `py -I` on POSIX.
Isolated interpreter mode prevents project/PYTHONPATH startup hooks from running
before the script can restrict imports.

```text
py -I scripts/evidence_nomination.py preflight --request <request.json> --project-root <project> --map-root <map-directory> --format json
py -I scripts/evidence_nomination.py nominate --request <request.json> --project-root <project> --map-root <map-directory> --out-dir <project>/.analyze-project-claims/nominations --format json
py -I scripts/evidence_nomination.py show --bundle <bundle.json> --format json
py -I scripts/evidence_nomination.py verify --bundle <bundle.json> --project-root <project> --map-root <map-directory> --format json
py -I scripts/evidence_nomination.py compile --bundle <bundle.json> --selection <selection.json> --project-root <project> --map-root <map-directory> --output <candidate.json> --format json
py -I scripts/evidence_nomination.py handoff --bundle <bundle.json> --selection <selection.json> --candidate <candidate.json> --project-root <project> --map-root <map-directory> --output <native.payload.json> --format json
```

Add `--record <persisted-v2-record.json>` to preflight, nominate, verify, compile,
and handoff for a claim target. A component target rejects an unexpected record argument.
`--format human` is the default. JSON mode emits one receipt on stdout and
sanitized diagnostics on stderr. CLI arguments are data, never shell commands.

Preflight verifies request structure, roots, accepted map, active engine, and
optional claim-record identity. It does not scan evidence or create output.
Nominate scans the bounded local corpus and creates two files:

- `<bundle-id>.bundle.json`: canonical UTF-8 JSON plus LF;
- `<bundle-id>.selection.json`: a bound empty reviewer template.

Edit the selection as an explicit reviewer action. An empty selection or null
reviewer input cannot compile. Keep the reviewed selection, candidate, and
extracted payload in the same directory as their bundle. These sidecars remain
outside accepted-map and formal validation/history directories.

## Review, compile, and hand off

1. Use `show` to inspect the nominations. In the generated selection, choose
   unique nomination IDs and explicitly write each evidence role, observed
   summary, and rationale. The reviewer label is informational, not authenticated.
2. Supply the complete native reviewer input for the target kind:
   - **Claim:** a scan-record v2 input. Each selection needs a unique evidence ID
     and an exact local file/line-range evidence item using `method=inspected`,
     the reviewed summary, and an explicit role binding to the target claim.
     Keep that claim's ID, statement, and element reference. The entire payload
     remains reviewer-authored, including statuses and limitations.
   - **Component:** a complete observation retaining every accepted component,
     element, component type, and target. Compilation adds selected local
     `lines:start-end` evidence only to the bound element, deduplicates exact
     evidence objects, and preserves conflicting observations and other fields.
     Do not supply claim evidence IDs. Roles and rationales remain in the sidecar.
3. Run `compile`. It replays the bundle, checks all three map identities and the
   exact raw selection bytes, and creates one candidate envelope. It does not
   run the native validator, append, reconcile, or accept operations.
4. Run the `handoff` arguments printed in the receipt. This rechecks the bundle,
   sources, selection bytes, and exact compiler result before extracting the
   native payload. It prints the appropriate native **validate** or **reconcile**
   command with expected map and payload digests. It never executes that command.
5. Run that native command separately when ready. The receipt's command is an
   argument array, not a shell-escaped string: invoke its script with `py` or
   `python3` and pass each argument separately, quoting paths for your shell.
   Native validation still decides semantic validity. Reconcile may create
   candidate/delta/history artifacts; map acceptance remains a separate action.

The native `reconcile`, v2 `validate`, and v2 `append` commands accept:

| Argument | Identity checked |
| --- | --- |
| `--expected-map-id` | Exact accepted-map ID |
| `--expected-map-canonical-sha256` | Canonical accepted-map payload digest |
| `--expected-map-file-sha256` | Full accepted-map file bytes, including formatting |
| `--expected-input-sha256` | Exact extracted native payload bytes |

Map guards are optional for ordinary existing invocations, but supplying any
requires all three. The payload guard requires the map guards. Generated
handoffs include all four. The native command hashes and parses one bounded
snapshot, then validates it with its existing schema authority. The recorder
retains its existing 5 MiB map/input limit; the reconciler guard caps reads at
8 MiB. Append rechecks
the map after evidence materialization; reconcile rechecks before each write.
Missing, invalid, changed, or partially specified expected identities refuse the
operation. Native guard failures use the native CLI's exit 2, while nomination
staleness uses exit 4. An unguarded invocation does not retain nomination guards.

To append a reviewed claim later, refresh the handoff, retain all four guard
arguments, change its native `validate` action to `append`, and explicitly supply
`--log-dir` (and optionally `--report-dir`). Compilation and handoff do not make
this decision or supply a history destination.

Freshness is established at replay/guard checks, not indefinitely. These checks
do not lock the whole project or make multiple reconcile writes one transaction.
If a map changes between reconcile writes, earlier candidate artifacts can
remain; inspect them before retrying. T4 still owes broader concurrent-filesystem
and cross-platform testing. Re-run handoff immediately before a downstream
operation when evidence may have changed.

### Development identity boundary

T3 rebuilds the embedded engine descriptor and package manifest to match its
changed native source. This is development integrity, not release approval or
acceptance of a new project map. Frozen T1 examples and dated v0.9.0 validation
records retain their original bytes. Current-code verification correctly marks
old recorder/engine identities stale. Runtime claim tests build fresh synthetic
records; they do not rewrite the historical examples or accept a real map.
Existing T1/T2 runtime bundles also require fresh nomination after code changes.
T6 still requires the exact release package, map reconciliation, explicit human
acceptance, and a fresh formal record.

## Replay and publication behavior

`show` checks closed structure, canonical self-integrity, local-path syntax,
references, and display safety. Its receipt says `self_integrity_only`: it does
not prove source freshness or authenticate who authored the file.

`verify` rechecks the active code/schema/Unicode identities and all three map
identities, rescans the approved roots, and compares the complete deterministic
bundle. Source edits, new/deleted corpus files, query/ranking changes, or code
and schema changes fail with exit 4. Keep the bundle in its output directory
when replaying: that directory is excluded from the corpus. Moving artifacts
inside scanned roots changes the scan layout and can invalidate replay.

Request files are input sidecars, not evidence. The scanner recognizes JSON
whose normalized gap request equals the bound request, including differently
formatted copies. It applies that rule during both nomination and verification,
so the original request's machine-specific path is not needed in bundle identity.
Such files still count as attempted input while being identified. Map directories,
record input paths, VCS directories, known skill installations, and the output
directory are excluded from evidence scanning.

Publishing uses complete temporary files and exclusive hard links. An existing
byte-identical bundle and untouched selection template yield `reused_identical`.
Different bytes are never overwritten. After a reviewer edits a selection,
use verify for freshness; repeating nominate into the same directory refuses
to overwrite that edited selection. A clean output directory permits a new
copy without erasing the reviewed one.

Bundle and selection publication are separate operations. If the second fails,
the first may exist. Exit-5 receipts report created artifacts and whether any
state changed; inspect them before retrying. No rollback is invented. Unsupported
hard-link filesystems fail closed rather than using a non-atomic overwrite.

## Filesystem and content boundaries

Outputs must stay inside the declared project, outside `validation/`, outside
map-root and installed-skill locations, and must not contain a search root.
The conventional `.analyze-project-claims/nominations/` directory is ignored by
Git because its excerpts may be private. Explicitly review any other output
location before retaining or publishing its files.

Reads walk ordinary directory components without following links. POSIX uses
anchored directory descriptors with `O_NOFOLLOW`; Windows uses reparse-point
opens and directory handles that deny replacement, plus file handles that deny
concurrent writes/deletion. File identities, sizes, and timestamps are compared
around reads, then admitted source bytes are rechecked before publication.
Windows ctime is excluded from cross-API comparison because Python's path and
handle APIs expose different meanings; identity/size/mtime and handle locks remain.

Explicit UNC and mapped-network-drive paths, traversal/ADS/device names, root
overlap, case collisions, and unsafe inputs fail closed. The scanner never
launches processes, calls network APIs, imports project code, accepts maps,
appends formal records, installs packages, or executes returned commands.
Interpreter startup and arbitrary remote-mounted POSIX filesystems are outside
that application-level guarantee; use a trusted interpreter and local disk.

Archive, binary/non-UTF-8/BOM, LFS, unsafe-control, recognizable secret, oversize,
and empty content receive aggregate exclusion codes. Rejected content and paths
are not echoed. Secret patterns cover private-key blocks, common credential
formats, and credential assignments; they are not a guarantee that every
possible secret can be recognized. Review excerpts before sharing.

The frozen budgets apply to file attempts, total bytes, matches, ranges, and
results. Additional traversal safeguards cap discovery at 25,000 entries and
64 directory levels; exceeding either refuses the operation with exit 2.
The ten-second deadline is checked throughout enumeration/read/matching and
before publication. A detected timeout returns exit 3 with no bundle; blocking
OS I/O must return before Python can check its deadline. Deterministic budget
truncation yields partial output, never a wall-time-selected prefix.

## Receipts and validation

Receipts include status/code/effect, changed/retryable, artifact path/hash,
target, nomination count, completeness, exclusions/truncations, `network=false`,
`accepted_state_changed=false`, next command, and this guide. Preflight and
errors may have null artifact/target fields where no validated artifact exists.

| Exit | Meaning |
| --- | --- |
| 0 | ready, complete, partial, zero nominations, identical reuse, inspected, verified, compiled, handoff prepared |
| 2 | invalid input or safety refusal |
| 3 | retryable local I/O or detected timeout |
| 4 | stale or tampered identity |
| 5 | publication/recovery failure; inspect actual surviving files |

Run development checks with:

```text
py -m unittest discover -s tests -p test_evidence_nomination_runtime.py -v
py -m unittest discover -s tests -p test_evidence_nomination_contracts.py -v
py -m unittest discover -s tests -p test_evidence_nomination_compile.py -v
```

The T1 golden bundle intentionally has a fixture-producer identity. Runtime
tests compare its request/corpus/query/nomination semantics, while runtime bundles
bind the actual code/schema/Unicode identities. Fixture and runtime bundle IDs
therefore differ. Tests cover both target types, replay, drift, input rejection,
budgets, no-clobber/recovery, UTF-8/CRLF, and process/network canaries. Compiler
tests also cover raw-review provenance, native guard refusals, and separate
synthetic downstream invocations. They do not establish scientific reliability
or complete T4's platform and race audit.
