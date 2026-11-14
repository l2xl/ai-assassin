---
kind: skill
description: How an answer asks the harness to run tools and how their results come back
default: true
---
# Tool calls
An answer is text, or tool calls, or text said beside tool calls: the object `{"kind": "text", "text": "…"}` or `{"kind": "calls", "calls": [...], "text": "…"}`, the `text` optional beside the calls. A text answer ends the turn and is your reply; a calls answer goes on with the next round.
Every call is an object whose `tool` names one of the tools defined to you, its other keys being the fields of that tool. The calls are applied in order and the first refused one stops the batch: the refusal comes back to you as the next prompt, with the results of the calls applied before it, for you to correct the call or answer in text.
What a call read or ran is not your answer but your next prompt: the harness places the results of the batch into the same session as the next message and the exchange goes on with your next answer, for a bounded number of rounds.
Subagents and workflows you launch are awaited: the turn lasts until they have reported and you have answered again, and only that last answer counts. A shell command left running in the background is killed when the turn ends, so await it instead.
