---
version: 1
id: git
type: policy
name: Git discipline
description: Git is the factual record - no history rewriting of shared branches, scoped commits, no bypassing hooks or reviews.
tags: [git, process]
applies_to:
  always: true
---
# Policy: Git discipline

Mandatory. Git is evidence; it must stay trustworthy.

1. Never force-push, rebase or otherwise rewrite the history of a shared branch
   (`main`, release branches) without explicit human approval.
2. Never bypass hooks, signing or required checks (`--no-verify`, disabling CI) to land a change.
3. Work happens on a branch; the default branch only receives reviewed, green changes.
4. A commit contains only changes inside the task's declared scope; unrelated edits are
   split out or reported, never smuggled in.
5. Commit messages state *what* changed and *why*; generated commits carry attribution.
6. Destructive operations (`reset --hard`, `clean -fdx`, branch deletion) on work you did
   not create require confirmation.
7. Secrets in Git are governed by the `secrets` policy.
