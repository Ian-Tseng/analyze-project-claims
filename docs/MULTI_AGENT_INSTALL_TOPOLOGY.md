# Multi-Agent Install Topology

`analyze-project-claims` and the producer skills are ordinary GitHub-distributed
skill packages. Codex, Claude Code, and other hosts do not share one automatic
installation directory or one activation lifecycle.

| Surface | Authority | What an update changes |
| --- | --- | --- |
| GitHub CLI standalone skill | `gh skill` metadata and one verified user-scope install | Files used by the next host invocation |
| Codex plugin/skill discovery | Codex installation and plugin cache | The next fresh Codex discovery/invocation |
| Claude Code skill/plugin discovery | Claude installation or repository configuration | The next fresh Claude Code discovery/invocation |
| Publisher checkout | Git branch, reviewed commit, tag, and release | Source candidate only; never an installed copy |
| Managed repair workflow | Caller policy, full workflow SHA, protected environments | One draft candidate PR only |

Never keep two visible same-name installations and call one of them “the”
managed copy. The producer updater fails closed on ambiguous installs, a pinned
copy, a modified package, source mismatch, or a publisher checkout. Updating one
host does not prove another host activated the same bytes.

On another PC, install from the exact public repository through that host’s
documented mechanism, verify the package manifest, start a fresh host process,
invoke the skill explicitly, and record the observed version/source. Claude
distribution documentation is not evidence that Claude discovered or invoked a
skill; activation needs a separate observed receipt.

The GitHub repair caller is repository-side automation. It does not make a
local skill installation self-modifying, and it is not executed merely because
a skill was selected. “Every time” means the documented maintenance tail runs
for supported managed invocations; hosts that skip, truncate, or do not execute
skill instructions remain outside that guarantee.
