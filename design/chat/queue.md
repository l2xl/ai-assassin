# Messages while a turn runs

**Messages while a turn runs.** A message sent from the reply line during a turn is **queued**
(Ctrl/⌘+Enter or the green `➤ send` chat pill): the line empties and the message stands at the end
of the log as a pending user message (`.chat-msg.user.queued`), a spinner in the left padding
its only mark of waiting, no hint above it, held by the server (`queue` of the chat) so every tab shows it. The AI takes it as soon as it
can: a turn of the harness's own rounds hands it to the model with the next round's prompt
(`The user wrote while you were working:` after the results) and shows it in its place among the
turn's blocks (`.chat-msg.user.delivered`, a `user` step); what the turn did not take — a
connector running the whole turn in one process, a turn ending on text — goes as the next turn of
the same session the moment the running one ends, every queued message a user message of its own.
Until taken, the message's `✕` mark withdraws it back into the reply line.

**Send now.** Every queued message of a running turn carries at its right, level with its first
line, a `➤ send` pill (`.queue-send`) of the strip's rounded shape: red border and text — it
stops the turn — with the triangle green — it sends. The two colours never carry the meaning
alone: the label and the triangle say it too. A click stops the turn keeping the queue
(`POST /api/turn/<UID>:<n>/stop` with `send`), so every queued message goes as the next turn of
the same session, the stopped turn shown as stopped before it; Ctrl/⌘+Shift+Enter in the reply line
queues the typed message and does the same.
