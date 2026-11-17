# Log tool

The log tool (`loglib.py`) reads back the record the server keeps of every item's chat, the live
conversation and the filed ones, whatever was pruned from a session. A turn is addressed as
`@UID turn N`, and its parts are its user messages, its steps and its reply.

- **Turns.** `{"tool": "log"}` lists the turns of the asking chat, `uid` — an item's UID, `@` or a
  glob such as `AREA-*` — those of the chats it names; newest first, one line each: address, time
  answered, step count, the first lines of the user's message and of the reply.
- **A turn.** `turn` lists its parts one line each; `step` returns one in full — a step by its
  number, `user` or `reply` — cut past a limit with the `offset` to go on from. A turn is read in
  one chat: a glob is refused.
- **Search.** `search` returns the parts holding every word, a quoted phrase as one, case
  ignored, in every chat or in those `uid` names: newest turn first, each as its address, time,
  what the part is and the text around the first word found.
- **Time range.** `since` and `until` keep a listing or a search to the turns answered in the range:
  a local date (a bare date as `until` standing for its last moment), a date-time or a span back
  from now (`3d`, `12h`, `30m`). A turn in flight has no answer time and falls out of a bounded one.
- **Withheld.** Text the user folded out and the result a security finding dropped are never
  returned nor found: a mark stands in their place, the dropped step keeping only its own call.

A broad question over the history is the `history` agent's: an off-context agent with the log
tool alone, reporting a summary over the exact turns it rests on.
