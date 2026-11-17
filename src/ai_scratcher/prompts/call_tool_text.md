---
kind: skill
description: How an answer is written as the content of the message, its calls as an object or in a fenced block
default: true
delivery: text
---
# Text answer
Your answer is the content of your message: the object `{"kind": "text", "text": "…"}` for a reply, or `{"kind": "calls", "calls": [...], "text": "…"}` for calls, the `text` optional beside them. Where your connection does not take the message as that object, write it plain: the reply as it is, or the list of calls in a single fenced block tagged `syngate`, the prose around that block being the text said beside them:
```syngate
[{"tool": "query", "uid": "@"},
 {"tool": "skill", "name": "syngate"}]
```
Calls written as native tool-use markup are not run: the answer is refused.
