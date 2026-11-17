---
kind: skill
description: How a request for a change reaches the item whose statement it details, and on to that item's separable children
default: true
---
# Delegation
A message asking for a change of the project — a feature, a requirement, a fix, a reworded behaviour — is a task for the item whose context fits it best: the narrowest item whose statement the task details, looked for among the anchored item, the items of its seed context and those the exchange names by `@UID`, which you `query` or read with `context` before you judge. A question or a discussion asking for no change stays in the anchored chat.
- Where an item already states what the task changes, that item is the fit.
- Where no item states it yet, the request becomes a new item first: `add` it under the best-fitting parent, its UID semantic and its statement condensed from the request by the DAG rules, so the request is never left as a loose paragraph.
- Make sure the fitting item's statement holds what the request asks — `edit` it where it does not — then hand the task on with `{"tool": "agent", "uid": "…"}`: the work goes on in that item's own chat and context, whose seed already carries the statement.
- Only when the fit is the anchored item itself does this turn do the work.
A task on an item with children starts with the analysis of their scope: read the children with `query` and judge which child scopes are separable — work that one child's context covers and that does not wait on its siblings — and hand each separable one on the same way. What spans several children, or joins their results, stays with you.
Prefer delegation for work needing wide reading or many rounds — a survey of many files, a long investigation, a change tried again and again: state the task as an item — an existing child, or a new one you `add` under the anchored item holding the exact instructions — and run it there with the agent call, so your session holds its report alone, not everything read on the way.
A report is all you receive of a delegated turn: its closing text and the cumulative change — every item and project file it changed named once, as it stands at the turn's end — never its calls, their results or its intermediate texts; the `log` tool reads those where you need one.
A report is evidence to review, not the outcome: check it against what the harness shows — the files changed, the tests run — before you build on it. A report opening with `[turn closed by the harness: …]` is of a turn ended by a limit, its task possibly unfinished: read what it did and what it left, then decide — finish the rest yourself, or delegate anew with a prompt corrected by what the report shows: narrower, naming what is done and what remains. Never send the same prompt again.
