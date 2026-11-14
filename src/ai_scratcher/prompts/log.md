---
kind: tool
description: Read back the steps of a turn of this chat from the chat's full record, one line each or one in full
calls:
  log:
    optional:
      turn: {type: integer}
      step: {type: integer}
      offset: {type: integer}
---
# Log
`{"tool": "log", "turn": 7}` lists the steps of turn 7 of this chat, one line each under its number; `{"tool": "log", "turn": 7, "step": 3}` returns that step in full, a long one cut with the `offset` to go on from (`{"tool": "log", "turn": 7, "step": 3, "offset": 20000}`).
- Read only and always allowed. It reads the record the server keeps of the chat, so a step cut out of your session — a tool result, the transcript of a subagent — is still there. A call that names no turn, or one with no steps recorded, is refused with the turns that have steps.
- Text the user folded out of the chat and a result a security finding dropped are not returned: a mark stands where they were.
