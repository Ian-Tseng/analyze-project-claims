# Managed Repair Walkthrough

This walkthrough traces one quality signal without collapsing its authority
boundaries.

1. A producer skill completes its substantive task and runs its local,
   consent-gated maintenance lease. A verified replacement affects the next
   invocation only.
2. The producer emits exactly one content-free `SKILL_OUTCOME_RECEIPT_V1`
   marker. Project paths, prompt text, logs, patches, and credentials are absent.
3. `analyze-project-claims` consumes the marker locally. `no_issue` is a no-op;
   a material signal creates one local proposal.
4. The user previews and separately confirms a bounded GitHub issue targeted to
   the receipt’s exact `Ian-Tseng` producer repository. The issue is evidence,
   not an instruction.
5. `Ian-Tseng` reviews the issue and applies `managed-repair-ready`. Nothing has
   repair or write authority yet.
6. The reusable workflow binds repository ID/name, issue node ID/number, issue
   body and label-state digests, `updated_at`, base SHA, policy digest, workflow
   SHA, run nonce, and expiry into one authorization ID.
7. A reviewer approves `managed-repair-agent`. The workflow refetches live state;
   any edit, relabel, base advance, policy change, pin change, or expiry stops it.
8. Codex receives only bounded untrusted evidence and a credential-free checkout.
   A preinstalled root-owned collector emits one guarded patch.
9. A fresh secret-free checkout applies the exact patch and runs the named
   validation profile. Candidate code has no supported write channel.
10. A reviewer approves `managed-repair-publish`. Live state is checked again.
    The workflow reconciles its deterministic branch/PR/comment identity, then
    creates at most one draft PR without force-push.
11. Human review decides evidence-map acceptance, merge, release, publication,
    managed update, and fresh activation. A draft PR is not a fix or release.

If the attempt reports an unknown remote outcome, do not relabel or rerun until
the authorization ID has been reconciled. If the central pin is suspected,
disable from the caller repository and lock both environments first.
