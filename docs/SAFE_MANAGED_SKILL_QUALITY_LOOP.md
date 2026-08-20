# How to Build a Safe Managed Skill Quality Loop

This guide captures the reusable design learned while extending a
GitHub-distributed agent skill with cross-skill feedback and managed updates.
It applies to other owner-managed skill repositories; it is not permission to
modify third-party packages or publish on their behalf.

## 1. Put the capability in the correct layer

A standalone skill is instructions loaded by a host. It cannot guarantee that
it runs after unrelated skills. Separate the system into:

1. a host-neutral receipt protocol;
2. an explicit portable consumer path;
3. an optional trusted adapter for each host;
4. a deterministic local state machine;
5. separately authorized owner contribution and release paths.

Do not parse unstable transcripts to simulate a lifecycle API. Prefer an exact
tail marker from the producer's result and the stable fields officially
supplied to the host hook.

## 2. Define exactly-once at the durable boundary

An LLM continuation cannot be guaranteed exactly once. Hosts can retry, route
differently, run multiple hooks concurrently, or stop a continuation. Define
the durable promise instead:

```text
proposal_key = SHA256(receipt_digest + analyzer_version)
```

Use a private atomic store and this lifecycle:

```text
RECEIVED -> VALIDATED -> READY -> CLAIMED(lease)
invalid                        -> QUARANTINED
expired lease       -> READY
CLAIMED -> PROPOSAL_COMMITTED -> CONSUMED
```

A crash before commit is recoverable after the lease. A crash after commit is
deduplicated by the proposal key. Recursion guards must include host state,
producer identity, and a bounded causal depth.

## 3. Minimize data before redacting

Use a closed enum-only schema with `additionalProperties: false`. Do not
collect raw content and then try to scrub it. Exclude prompts, transcripts,
paths, URLs, logs, tools, environment data, findings, diffs, patches,
attachments, credentials, and arbitrary strings by construction.

Bound bytes, counts, TTL, causal depth, queue size, and hook runtime. Mark
producer identity as declared unless a trusted host actually attests it.

Reject future-dated receipts beyond a small clock-skew allowance, reclaim
expired and terminal queue entries, and prove rollover past the nominal queue
limit. A bound without reclamation is a lifetime failure counter, not a queue.

## 4. Separate every permission

Keep these independent:

- local receipt persistence;
- local proposal creation;
- public or private contribution;
- owner triage;
- draft PR generation;
- component-map acceptance;
- merge;
- release;
- installed replacement;
- fresh activation;
- analytics and problem reporting.

A preview must bind the exact payload and destination to an approval ID. Public
visibility needs an additional per-submission confirmation. Automatic public
issues carrying updated files are unsafe; send only bounded enum/package
identity and let a protected owner workflow reproduce the problem.

Bind one contribution ID to at most one outbound attempt. Persist
`ATTEMPTING` before the request and treat timeouts or malformed responses as
unknown outcomes that require reconciliation, never blind retry.

## 5. Keep one update authority

Plugin managers own plugin packages. Native skill installers own standalone
copies. Manual and pinned copies remain manual. If two same-name installs are
visible, fail closed and provide a read-only doctor that lists the competing
copies. Never delete, force, unpin, or guess.

Run maintenance after the substantive result so update outages cannot block
the product. “After every use” can mean the local maintenance entry point runs;
remote checks should retain a lease. Activate replacement on the next fresh
invocation.

## 6. Prevent automation from approving its own evidence

When a component map or similar evidence authority protects the repository,
agent patches may create a map-pending draft but must not edit or accept that
authority. The owner applies the draft, reconciles the exact current tree,
reviews the delta, explicitly accepts the candidate, and then runs a second
unchanged reconciliation plus formal preflight.

The reconciler must compare its identity fields as well as semantic/source
fields. Otherwise instruction-only changes can be reported unchanged while a
formal scanner rejects the stale map.

## 7. Test and release in evidence stages

Use red tests for:

- identity-only component-map drift;
- unknown/content-bearing receipt fields;
- expiry, replay, concurrent claims, and crash recovery;
- hook recursion, duplicate turns, timeout, routing failure, and veto recovery;
- preview equality, stale approval, revoked consent, and public visibility;
- exact owner/repository/actor/label/base binding;
- map-pending draft to human acceptance;
- package integrity and one update authority;
- release N to N+1 replacement and fresh activation.

Then keep deployment states separate:

```text
implemented -> locally tested -> commit-bound CI -> published
-> installed postcondition -> fresh activation -> host observed
```

Do not claim the next state from the previous one. Preserve immutable failing
releases as evidence instead of rewriting their tags.

## 8. Reusable release order

1. Repair existing repository invariants before adding a gate that enforces them.
2. Freeze schemas and local state transitions.
3. Pass portable explicit E2E with two unrelated producer fixtures.
4. Add owner contribution with separate consent and exact intake.
5. Add one host adapter and document its weaker guarantee.
6. Reconcile and explicitly accept the component map.
7. Synchronize VERSION, package metadata, plugin metadata, manifest, citation, changelog, and docs.
8. Run focused tests, full tests, package verification, engine verification, formal preflight, and plugin validation.
9. Commit and run remote CI.
10. Publish immutable release artifacts.
11. Test install, older-to-newer replacement, and fresh invocation per host.
12. Record every unobserved boundary in an evidence log.
