# Stop

While a turn runs — a single answer, or one with tool calls, subagents or a workflow — the log ends
with the turn's blocks so far and its **activity line** (`.turn-activity`) growing live, and the chat pill is a
`■ stop` button (`.chat-stop`, red; Ctrl/⌘+. is its keyboard twin) while the reply line is empty: the chat
can be neither hidden nor its fold marks switched until the turn ends. One press turns it into
`stopping…`, disabled, until the outcome lands. A plain stop sends nothing more: the messages
queued meanwhile are withdrawn back into the reply line (a queued message's `➤ send` is the stop that sends).
The turn itself runs on the server as
`<UID>:<n>` of the item's chat, so a reload of the page, or
any other page showing the item, re-attaches to it and shows its progress and reply when they come.
The outline mirrors the state: the row of an item that has a chat carries a chat state mark; a hidden chat's `▾` carries the same mark.

**Stop is an emergency halt.** The chat's hide mark is a `■ stop` button while the turn runs
(`POST /api/turn/<UID>:<n>/stop`); the user means "nothing more happens, from now", so the server
acts in this order, the instant the request lands: the turn is marked stopped, which closes its
gate — no tree call, test run or delegation of the turn is applied past that mark, a batch
half-applied stays half-applied; the turns it delegated are stopped the same way; the test run it
awaits is cancelled; a shell command it runs is killed with its process group; and the connector is told to interrupt. Either way the
dispatch fails as a connection error; the steps collected and the calls applied before the stop
stay, and the turn ends marked as stopped — a `stopped` message in the log, not an error. A stop
that lands before the connector spawned its process spawns none.
