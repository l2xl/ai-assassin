---
kind: skill
description: How a turn on an item with children shares the work among them
default: true
---
# Delegation
A task on an item with children starts with the analysis of their scope: read the children with `query` and judge which child scopes are separable — work that one child's context covers and that does not wait on its siblings. Delegate each separable one with `{"tool": "agent", "uid": "AREA-010", "prompt": "…"}`, its prompt stating that child's task; the agent calls of one batch run in parallel and their reports come back as your next prompt. What spans several children, or joins their results, stays with you.
When you run your own subagents instead, the first line of every subagent prompt names its target item as `@UID`, so its report and transcript are shown in that item's chat too.
