# Component Evidence Protocol v2

The component-evidence engine is a versioned internal module of
`analyze-project-claims`, not a separately discoverable skill.

The checked-in `component-evidence-engine.json` descriptor binds the provider
kind, engine version, map schema, receipt protocol, and exact engine code,
schema, and template hashes. Its `engine_digest` is the SHA-256 digest of the
canonical descriptor without the digest field. The enclosing package manifest
covers the descriptor itself.

Receipts identify the provider as `embedded` and bind the engine digest. A
semantic-only analyzer change does not change this digest. Any engine file,
schema, template, descriptor metadata, or protocol change requires a new
descriptor and invalidates receipts bound to the prior engine identity.

The reconciler compares the observation's objective, scope, authority,
`skill_sha256`, mapper version, components, relations, and source hashes. A
change to any of those identity or contract fields produces a promotable
candidate; it cannot be reported as `checked_unchanged`.

Maintainers rebuild and then verify the descriptor before package-manifest
generation:

```text
<python-3> scripts/reconcile_component_map.py build-self --write
<python-3> scripts/reconcile_component_map.py verify-self
```

The engine emits structural component evidence only. It does not make semantic
project recommendations, perform updates, use network transports, or create
owner reports. Existing v1 accepted maps remain historical authority; protocol
v2 binds them to an engine identity without silently rewriting them.
