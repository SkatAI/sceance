---
name: recap
description: Use when the user types /recap or asks for a recap/summary of recent work, what's been done, or where things stand on the sceance project.
---

# Recap

Summarize recent development work on sceance. **Recap ALL sessions across
worktrees and branches, not just the current chat window** — work happens in
parallel worktrees and a single-branch view misses most of it.

## Gather

Run these and synthesize — don't dump raw output:

1. **Worktrees** — `git worktree list` to see every active checkout.
2. **Recent commits across all branches** —
   `git log --all --oneline --since="<window>" --date=short --pretty=format:'%cd %h %s'`
   (default window: last 7 days, or whatever the user asks for).
3. **Uncommitted / in-flight work** — for each worktree, `git -C <path> status -s`
   and `git -C <path> diff --stat` to surface work not yet committed.
4. **Changelog** — the top of `changelog.md` for the user-facing framing of
   recent changes.

## Report

Group by theme or branch, newest first. For each thread: what changed, why, and
its state (shipped to `production` / merged to `main` / in progress /
uncommitted). Call out anything left dangling (uncommitted changes, branches
not merged, failing or skipped work). End with a one-line "where things stand."

If the user asked specifically about latency or a session's performance, that's
a different task — use the session latency runbook instead of this recap.
