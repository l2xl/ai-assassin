---
kind: skill
description: How a plain answer carries its tool calls in a fenced block
default: true
delivery: text
---
# Call block
Where your answer is not taken as the object itself, write it plain: the reply as it is, or the list of calls in a single fenced block tagged `syngate`, the prose around that block being the text said beside them:
```syngate
[{"tool": "query", "uid": "@"},
 {"tool": "skill", "name": "syngate"}]
```
