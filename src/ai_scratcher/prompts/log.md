---
kind: tool
description: Read back the record of every item's chat -- turns, their user messages, steps and replies -- list, read in full or search them by words and time
calls:
  log:
    optional:
      uid: {type: string}
      turn: {type: integer}
      step: {anyOf: [{type: integer}, {enum: [user, reply]}]}
      offset: {type: integer}
      search: {type: string}
      since: {type: string}
      until: {type: string}
---
# Log
`{"tool": "log"}` lists the turns of this chat, newest first, one line each with the time it was answered, its step count and the first lines of the user's message and the reply; `{"tool": "log", "uid": "AREA-*"}` lists those of the chats a UID or glob names, `@` standing for this one.
`{"tool": "log", "turn": 7}` lists the parts of turn 7 of this chat — its user messages, its steps under their numbers, its reply — one line each; `{"tool": "log", "turn": 7, "step": 3}` returns step 3 in full, `"step": "user"` or `"step": "reply"` that part, a long one cut with the `offset` to go on from (`{"tool": "log", "turn": 7, "step": 3, "offset": 20000}`). With `uid` the turn is read in that item's chat, never a glob.
`{"tool": "log", "search": "queue \"stop button\""}` returns the parts holding every word, a quoted phrase as one, in every chat or in those `uid` names, each as its address and the text around the match.
`since` and `until` keep a listing or a search to the turns answered in that range: a date (`2026-11-17`), a date-time (`2026-11-17 14:30`) or a span back from now (`3d`, `12h`, `30m`).
- Read only and always allowed. It reads the record the server keeps of every chat, the filed conversations included, so a step cut out of your session — a tool result, the transcript of a subagent — is still there.
- Text the user folded out of the chat and a result a security finding dropped are not returned: a mark stands where they were.
- A broad question over the history — what was decided about a feature, when and why — goes to the `history` agent rather than through many reads of your own: `{"tool": "agent", "name": "history", "prompt": "…"}` reports a summary over the exact turns it rests on.
