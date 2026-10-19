---
kind: tool
description: Read the project's git history and record changes in it, never erasing what git holds
calls:
  git:
    required: [command]
---
# Git
`{"tool": "git", "command": "log --oneline -5"}` runs git with the command line after the word `git`, split into words as a shell splits them but never run by one, in the project root; its exit status and output come back as your next prompt.
- It reads — status, diff, log, show, blame, grep, ls-files, shortlog, describe, rev-parse — and records — add, commit, mv, rm, restore --staged, branch, tag, switch, merge, cherry-pick, revert.
- Nothing erasing or rewriting what git holds runs, the refusal coming back as your next prompt: any other command, an option ahead of the command, amending, deleting, renaming or force-moving a branch or a tag, forcing an add, a move or a removal, aborting a merge and restoring the work tree are refused. Write an option's value as a word of its own.
- mv and rm take no path under syngate/ — the items change only through the tree calls — and no glob or pathspec magic; the history of syngate/ is yours to read.
- A commit of yours stages what belongs to one change and condenses it in a subject the way the log does; a subject opening with the word `Review` is the review commit's, and review stamps are never committed together with content.
