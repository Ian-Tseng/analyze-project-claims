# Session recovery and retained controller handoffs

Use when a host-capacity failure or an owner-requested session handoff blocks
claims review. Apply the [host protocol](subagent-host-protocol.md) first.
This guide adds diagnosis and handoff instructions; it implements no host
release operation, scheduler, controller migration or new execution authority.

## Identify the failing layer

Keep front-end process state, server ownership, native goal status, reviewer
capacity and project-controller state separate. A visible window or exit code 0
does not prove a successful resume. A completed agent does not prove released
capacity. Use the actual host's close operation only when available and eligible;
interrupting, archiving or deleting lock files is not equivalent.

Inspect targeted process arguments and tool-host ancestry. Record process
identity or creation time as well as a PID, which may be reused. Scope startup
logs to the relevant thread, process and time interval; exclude unrelated
conversations and secrets. A later command with different arguments does not
establish who launched it or why the original process exited.

Check the installed client and running server separately. Command help may exit
before ordinary argument-conflict validation. Validate a proposed command with a
harmless parser path that cannot start work, where available, and state that
this does not test actual session recovery. Do not combine an approval/sandbox
preset with incompatible explicit flags merely because both appear in help.

For an interactive waiting launcher, distinguish requested, waiting, started,
exited and recovered states. An input EOF is not owner confirmation. Recheck the
actual process and state before reporting; preserve failed attempts and stop
identical relaunches when no new evidence changes the next action.

## Same-thread writer conflicts

A standalone, in-process resume error reporting that the thread already has an
active writer establishes a persistence-ownership conflict. It does not establish
a missing standalone flag, a crash, or an owner mistake. Front-end exit alone is
not evidence that the shared server released its writer.

The [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server#unsubscribe-from-a-loaded-thread),
consulted 2026-10-06, describes unloading after the last subscriber is gone and
there has been no thread activity for 30 minutes. Treat that as a documented
condition, not verification of an installed server or a guaranteed recovery
interval. Another subscriber or continuing goal activity can prevent idleness;
elapsed time alone does not prove release. `thread/unsubscribe` affects only the
calling connection, so a new observer cannot use it to detach other clients.

Preserve unrelated sessions and jobs. Do not force ownership by deleting locks,
archiving descendants, or restarting a shared daemon without applicable user
authority. Stop dependent execution when a supported release or observation
capability is unavailable. Do not present an immediate quit/resume sequence as a
verified fix without actual evidence of handoff.

## Owner-requested move to another session

A fresh conversation is an option when the owner requests a different session.
It avoids requesting that same conversation's writer, but does not prove free
reviewer capacity, controller compatibility or successful takeover. Never start
replacement conversations autonomously to evade host limits or replenish trial,
repair, dispatch or spawn allowances.

Before writing project state, verify that the old coordinator is quiescent and
reconcile its actual operations. Preserve the original objective, exact
controller and journal, pending tokens, roles, cumulative budgets, failed
histories, accepted claims, unreviewed results and manual gates. Recover unknown
effects without replay. A native goal's lifecycle is separate: an old blocked
goal does not automatically transfer, and creating a new goal grants no new
project execution allowance.

Use a supported ownership/rebinding procedure if the existing controller requires
one. If none applies, retain the blocker instead of editing the journal or
inventing a reviewer association, READY response or review result. Genuine
independent claims review remains required before dependent work.

## Record progress and limits

Classify each recovery turn as concrete progress, a verified wait on an actual
live operation, or no progress. Another status file is not recovery. Apply the
host's actual blocked/pause rules; do not pause without an owner request or treat
another continuation as verified inactivity. Recheck source freshness after a
handoff or guidance update. Preserve old receipts rather than silently replacing
their source hashes.

These instructions do not establish successful writer release, reviewer-capacity
recovery or migration on any particular host. Report command validation,
installation, client discovery, runtime invocation and recovery as separate
observations. Installing a new package does not prove that an already-running
session has loaded it; verify the active catalog on its next invocation.
