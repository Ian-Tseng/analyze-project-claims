# Local evidence nomination development CLI

T2 provides a repository-local, standard-library implementation of `preflight`,
`nominate`, `show`, and `verify`. It is development code in `scripts/`, not part
of the installed v0.9.0 package. T3's compile/adapters and downstream guards,
T4's broader adversarial/cross-platform audit, and T6 release authority remain
pending. Search results propose excerpts; they do not establish claim status.

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
```

Add `--record <persisted-v2-record.json>` to preflight, nominate, and verify for
a claim target. A component target rejects an unexpected record argument.
`--format human` is the default. JSON mode emits one receipt on stdout and
sanitized diagnostics on stderr. CLI arguments are data, never shell commands.

Preflight verifies request structure, roots, accepted map, active engine, and
optional claim-record identity. It does not scan evidence or create output.
Nominate scans the bounded local corpus and creates two files:

- `<bundle-id>.bundle.json`: canonical UTF-8 JSON plus LF;
- `<bundle-id>.selection.json`: a bound empty reviewer template.

T2 intentionally has no `compile` command. Edit the selection only as an
explicit reviewer action; an empty template grants no acceptance authority.
T3 will validate those choices and produce the two different candidate types.

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
| 0 | ready, complete, partial, zero nominations, identical reuse, inspected, verified |
| 2 | invalid input or safety refusal |
| 3 | retryable local I/O or detected timeout |
| 4 | stale or tampered identity |
| 5 | publication/recovery failure; inspect actual surviving files |

Run development checks with:

```text
py -m unittest discover -s tests -p test_evidence_nomination_runtime.py -v
py -m unittest discover -s tests -p test_evidence_nomination_contracts.py -v
```

The T1 golden bundle intentionally has a fixture-producer identity. Runtime
tests compare its request/corpus/query/nomination semantics, while runtime bundles
bind the actual code/schema/Unicode identities. Fixture and runtime bundle IDs
therefore differ. Tests cover both target types, replay, drift, input rejection,
budgets, no-clobber/recovery, UTF-8/CRLF, and process/network canaries. They do
not establish scientific reliability or complete T4's platform and race audit.
