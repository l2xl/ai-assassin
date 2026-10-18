---
kind: skill
description: How a request for a change reaches the item whose context fits it best
default: true
---
# Task routing
A message asking for a change of the project — a feature, a requirement, a fix, a reworded behaviour — is a task for the item whose context fits it best: the narrowest item whose statement the task details, looked for among the anchored item, the items of its seed context and those the exchange names by `@UID`, which you `query` or read with `context` before you judge. A question or a discussion asking for no change stays in the anchored chat.
- Where an item already states what the task changes, that item is the fit.
- Where no item states it yet, the request becomes a new item first: `add` it under the best-fitting parent, its UID semantic and its statement condensed from the request by the DAG rules, so the request is never left as a loose paragraph.
- Then hand the task on with `{"tool": "agent", "uid": "…", "prompt": "…"}` to the fitting item — new or found — its prompt stating the whole task, so the work goes on in that item's own chat and context; answer with what its report tells.
- Only when the fit is the anchored item itself does this turn do the work.
