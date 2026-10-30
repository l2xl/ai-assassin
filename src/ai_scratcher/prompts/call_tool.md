---
kind: skill
description: How an answer asks the harness to run tools and how their results come back
default: true
---
# Tool calls
An answer is plain text, or tool calls, or text said beside tool calls. A structured answer is the object `{"kind": "text", "text": "…"}` or `{"kind": "calls", "calls": [...], "text": "…"}`, the `text` optional beside the calls; a plain one carries the list in a single fenced block tagged `syngate`, the prose around that block being its text:
```syngate
[{"tool": "query", "uid": "@"},
 {"tool": "skill", "name": "syngate"}]
```
Every call is an object whose `tool` names one of the tools defined below, its other keys being the fields of that tool. The calls are applied in order and the first refused one stops the batch: the refusal comes back to you as the next prompt, with the results of the calls applied before it, for you to correct the call or answer in text.
What a call read or ran is not your answer but your next prompt: the harness places the results of the batch into the same session as the next message and the exchange goes on with your next answer, for a bounded number of rounds.
Subagents and workflows you launch are awaited: the turn lasts until they have reported and you have answered again, and only that last answer counts. A shell command left running in the background is killed when the turn ends, so await it instead.
