# Claude Code Other-PC Checklist

This checklist tests the portable explicit path. It does not test the Codex
plugin hook, and no Claude hook adapter is claimed in this release.

## Install and discover

On the other computer, record OS and Claude Code version, then run:

```powershell
gh skill install Ian-Tseng/analyze-project-claims `
  skills/analyze-project-claims/SKILL.md `
  --agent claude-code --scope user
gh skill list --agent claude-code --scope user --json skillName,sourceURL,scope,version,pinned,path
gh skill update analyze-project-claims --dry-run
claude --version
claude
```

Use a fresh Claude session if the top-level skills directory was created after
Claude started. Inside Claude Code:

1. Run `/skills` and confirm the exact `analyze-project-claims` name.
2. Invoke `/analyze-project-claims` on a disposable local fixture.
3. Run a disposable compatible producer fixture; never copy a real-project
   receipt between machines.
4. Invoke:

   ```text
   /analyze-project-claims consume the exact SkillOutcomeReceipt marker from
   the prior response and create one local proposal; do not submit anything.
   ```

5. Verify `QUALITY_PROPOSAL_READY`, one proposal ID, replay deduplication, and
   no network action.
6. Record Claude version, OS, install/list/update commands, invocation,
   bounded result, exit status, and installed source identity in
   `docs/CLAUDE_CODE_E2E_LOG.md`.

Receipts, proposals, consents, and state remain machine-local. Until this is
observed, public documentation may claim Claude package distribution only—not
Claude discovery, invocation, automatic continuation, or live replacement.

## Replacement evidence

After a later immutable release exists:

1. install the older release in an isolated user profile;
2. observe it in a fresh Claude session;
3. run the real managed update;
4. verify source identity, version, and manifest postconditions;
5. start another fresh Claude session and observe the new version;
6. record limitations, including any persistent-session caching.
