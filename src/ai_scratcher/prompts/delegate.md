---
kind: skill
description: How a turn on an item with children shares the work among them
default: true
---
# Delegation
A task on an item with children starts with the analysis of their scope: read the children with `query` and judge which child scopes are separable — work that one child's context covers and that does not wait on its siblings. Delegate each separable one with `{"tool": "agent", "uid": "AREA-010"}` — its statement and seed context are that child's task, the child being the active item of its own seed context, a short `prompt` adding only a detail the tree does not hold; the agent calls of one batch run in parallel and their reports come back as your next prompt. What spans several children, or joins their results, stays with you.
A report is evidence to review, not the outcome: check it against what the harness shows — the files changed, the tests run — before you build on it. A report opening with `[turn closed by the harness: …]` is of a turn ended by a limit, its task possibly unfinished: read what it did and what it left, then decide — finish the rest yourself, or delegate anew with a prompt corrected by what the report shows: narrower, naming what is done and what remains. Never send the same prompt again.
When you run your own subagents instead, the first line of every subagent prompt names its target item as `@UID`, so its report and transcript are shown in that item's chat too.
