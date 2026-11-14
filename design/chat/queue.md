# Messages while a turn runs

**Messages while a turn runs.** A message sent from the reply line during a turn is **queued**
(Ctrl/⌘+Enter): the line empties and the message stands at the end of the log as
a pending user message (`.chat-msg.user.queued`, `queued — goes to the AI at its next step`),
held by the server (`queue` of the chat) so every tab shows it. The AI takes it as soon as it
can: a turn of the harness's own rounds hands it to the model with the next round's prompt
(`The user wrote while you were working:` after the results) and shows it in its place among the
turn's blocks (`.chat-msg.user.delivered`, a `user` step); what the turn did not take — a
connector running the whole turn in one process, a turn ending on text — goes as the next turn of
the same session the moment the running one ends, every queued message a user message of its own.
Until taken, the message's `✕` mark withdraws it back into the reply line. The send pill of a
running turn reads **`➤ send!`** (Ctrl/⌘+Shift+Enter): stop, send, continue —
the typed message is queued and the turn stopped at once, so the message goes as the next turn of
the same session, the stopped turn shown as stopped before it.
