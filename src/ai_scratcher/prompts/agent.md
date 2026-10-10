---
kind: tool
description: Delegate a task to an item's chat, run as a turn of its own
---
# Agent
`{"tool": "agent", "uid": "AREA-010", "prompt": "…", "model": "…", "effort": "…", "modes": ["edit"]}` runs a turn of the named item's chat with `prompt` as its message, anchored at that item with its own seed context; "@" stands for the anchored item. `model`, `effort` and `modes` are optional, the setup of this turn applying where they are left out. Every agent call of a batch runs in parallel after the batch's other calls; this turn awaits them all and their final reports come back as your next prompt, one line `- agent UID: report` each. An item already running a turn refuses the call — the anchored item among them, since it runs this one.
