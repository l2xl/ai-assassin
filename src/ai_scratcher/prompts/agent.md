---
kind: tool
description: Delegate a task to an item's chat, run as a turn of its own
calls:
  agent:
    required: [uid, prompt]
    optional:
      model: {type: string}
      effort: {type: string}
      modes: {type: array, items: {type: string}}
      background: {type: boolean}
---
# Agent
`{"tool": "agent", "uid": "AREA-010", "prompt": "…", "model": "…", "effort": "…", "modes": ["edit"], "background": true}` runs a turn of the named item's chat with `prompt` as its message, anchored at that item with its own seed context; "@" stands for the anchored item. `model`, `effort`, `modes` and `background` are optional, the setup of this turn applying where they are left out. Every agent call of a batch runs in parallel after the batch's other calls; this turn awaits them all and their final reports come back as your next prompt, one line `- agent UID: report` each. An item already running a turn refuses the call — the anchored item among them, since it runs this one.
With `background: true` the call is not awaited: it is answered at once with `- agent UID: started in the background (turn UID:n)`, and you may answer and end your turn while the subagent runs, the user being free to write meanwhile. Its report then reaches you ahead of the user's next message.
