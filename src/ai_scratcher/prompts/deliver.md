---
kind: skill
description: How a task that reworks items is carried into the project's tests and sources
default: true
---
# Delivery
A task that adds or rewords items is a task on the project: the statements are its specification, and the turn is done when the project matches them, not when the items do. Once the statements are settled, carry them into the project in the same turn, the way the tree's test feature — `test: enabled|disabled` under Tree features in the seed context — sets:
- Enabled: write or rework the tests of every changed leaf first, each a routine tagged with the leaf's UID and, for a named binding, its name declared in the leaf's `tests`, so the tests state the leaf as it now reads; then change the key source files the items list until the `test` call on the reworked items passes.
- Disabled: the tree awaits no tests. Change the key source files the items list to match the statements; whether the project's existing tests need to follow is your judgement, and the `test` call still runs the routines tagged with the items, where the project has any. Items that list no sources are, on their own, the whole deliverable.
What the turn cannot complete — a source neither listed nor found, a test that cannot pass for a reason outside the task — it states in its answer rather than leaving the items ahead of the project.
