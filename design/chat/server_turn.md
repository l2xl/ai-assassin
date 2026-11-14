# Turn

A turn is a server-side job of the item's chat, addressed as `<UID>:<n>` (`POST /api/turn` starts
it and refuses a second turn of the same item, `GET /api/turn/<UID>:<n>?wait=<s>` awaits it,
`POST /api/chat` is the same exchange awaited in one request). It lasts until the connector's
process exits — by then every subagent and workflow launched in the turn has reported and the model
has answered again, the output of its last answer being the turn's answer — and its reply lands in the chat the server holds, so every page showing the item
picks it up, a reloaded one included; while any turn runs a page keeps one long poll out for the
next change of the chats (`GET /api/chats?since=<version>&wait=<s>`), one connection however many
chats are open. A turn is a tree of steps closed by an answer, never the answer alone:

- **Steps.** `message` (an intermediate answer of the model), `reasoning` (its exposed thinking), `tool` (name, input, result, duration),
  `calls` (the syngate calls applied, each result line paired with its call in `inputs`), `diff` (the files the turn changed, with hunks), `agent` (a
  subagent: its prompt, the item it is anchored at if any, its own steps and its final report) and
  `workflow` (opaque: input and result). The connector streams every event into the turn as it
  happens, and each appended step bumps the chats version, so the pages render the progress live
  rather than a spinner. The connector closes the turn with a `usage` step — `seconds`, `cost_usd`,
  `input_tokens`, `output_tokens` as the CLI's `result` event reports them — which the page folds
  into the activity line; the dispatch's `(reply, session)` shape stays as it is.
- **Reasoning is requested whenever it may be had.** The harness always asks the connection to
  expose the model's reasoning when the call mode allows it, and records it only when it comes. For
  the Claude Code connector every model offers the effort levels, Haiku included, yet whether the
  model exposes its reasoning still depends on the model and the effort — so `reasoning` steps are
  optional in every transcript, never promised.
