# Lifecycle receipt interpretation

`product-lifecycle` owns isolated install, update, activation, report-preview,
rollback, and cleanup execution. `analyze-project-claims` only consumes the
resulting `LifecycleVerificationReceipt`; the analyzer has no import or command
path to the executor.

## Interpret a receipt

```powershell
py -3 .\skills\analyze-project-claims\scripts\lifecycle_receipt.py `
  --format json interpret `
  --receipt .\lifecycle-verification-receipt.json
```

The consumer verifies the aggregate digest, every phase digest, the phase
chain and order, status invariants, and the explicit no-publish, no-report-send,
and no-live-install boundaries. It reports check status, claim status, evidence
method, and strongest safe claim separately. `COMPLETE` applies only to the
receipt's exact product, releases, adapter, target, platform, and phases; it is
not a general `E2E PASS`.

`RECOVERED` is also not a pass. It proves the disposable installation was
restored and cleaned after a failure while preserving the failed phase as
counterevidence.

## Request missing evidence

For `INCONSISTENT` or `EVIDENCE_GAP`, produce a digest-bound request:

```powershell
py -3 .\skills\analyze-project-claims\scripts\lifecycle_receipt.py `
  --format json followup `
  --receipt .\lifecycle-verification-receipt.json `
  --prior-request .\earlier-followup-request.json
```

The only allowed action in a request is `read_only_plan`. It does not approve
execution, cleanup, publication, live installation changes, or report sending.
Pass each earlier request in order. If the same finding and evidence need
repeats, stop immediately with `RECONCILIATION_STALLED`. Stop after three
distinct cycles even when the findings differ. A person then decides whether
to change scope, repair the product, collect different evidence, or stop.

## Automatic routing boundary

An agent should select this route when the user supplies a lifecycle receipt or
asks whether lifecycle evidence is consistent. Selection does not imply
execution. Any later lifecycle action routes back to `product-lifecycle`, which
must return a new exact plan and obtain its own digest approval.
