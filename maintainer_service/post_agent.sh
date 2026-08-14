#!/usr/bin/env bash
# Trusted post-Codex collector, installed root-owned before the isolated agent runs.
set -euo pipefail

if [[ "$(/usr/bin/id -u)" -ne 0 ]]; then
  echo "post-agent collector must run as root" >&2
  exit 1
fi

umask 077
readonly trusted_root="/opt/analyze-project-claims-maintainer"
readonly workspace="${GITHUB_WORKSPACE:?}"
readonly output_root="${RUNNER_TEMP:?}"

export PATH="/usr/bin:/bin"
export HOME="${output_root}/post-agent-home"
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_OPTIONAL_LOCKS=0
unset BASH_ENV CDPATH ENV GIT_EXEC_PATH GIT_OBJECT_DIRECTORY
unset LD_LIBRARY_PATH PYTHONHOME PYTHONPATH

/usr/bin/mkdir -p -- "$HOME"
readonly alternate_index="$(/usr/bin/mktemp "${output_root}/agent-index.XXXXXX")"
cleanup() { /usr/bin/rm -f -- "$alternate_index"; }
trap cleanup EXIT
/usr/bin/rm -f -- "$alternate_index"
export GIT_DIR="${trusted_root}/git"
export GIT_WORK_TREE="$workspace"
export GIT_INDEX_FILE="$alternate_index"
cd "$workspace"
/usr/bin/rm -rf -- .agent-maintainer
/usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c diff.external= read-tree HEAD
/usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c diff.external= add -A
/usr/bin/python3 -I "$trusted_root/patch_guard.py" \
  --repo-root "$workspace" \
  --staged \
  --json-out "$output_root/patch-guard.json"
/usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c diff.external= \
  diff --cached --binary --full-index --no-ext-diff > "$output_root/candidate.patch"
/usr/bin/test -s "$output_root/candidate.patch"
(cd "$output_root" && /usr/bin/sha256sum candidate.patch > candidate.sha256)
/usr/bin/chmod 0444 -- \
  "$output_root/candidate.patch" \
  "$output_root/candidate.sha256" \
  "$output_root/patch-guard.json"

