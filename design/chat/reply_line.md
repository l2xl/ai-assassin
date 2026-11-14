# Reply line

**In the reply line.** Every panel holds the empty reply line (`.chat-input`) under its
description at all times, outside the Tab order while at rest (it joins it with the open chat or
the editor). Its top rule and hint appear with the block's border, on hover or focus; at rest the
line is blank. The hint tells the line's state:

| State | Hint |
|---|---|
| no chat shown in the block | `Type a message to start new chat` |
| open chat | `Type message · Ctrl/⌘+Enter sends` |
| a turn of the item runs | `Waiting AI response` |

While the turn runs a spinner (`.reply-wait`) stands left of the field, in the block's left
padding, so it never overlaps the typed text; it shows whether the chat is open or hidden.

While the line of the open chat holds text, the clear mark (`.reply-clear`, `✕`, titled `clear
the message`) stands on the block's right border line level with the line's first line — the
border-mounted place and round shape of the message marks, the left padding being the spinner's
and the mention hint opening under the field's left edge, so neither ever meets it. It empties
the line and the text the tab keeps for it, the focus back
in the line and an open mention hint closed; the log, the session and the item are untouched.

Entering the line — by click or by focus — opens the chat: the log and the controls appear, and
a message sent from there starts the exchange without touching the item. When the item's chat
holds messages and is shown nowhere in this tab, entering the line is the choice of a new
conversation: the log shown is empty (the tab's view is `fresh`), and the previous conversation
is filed behind `▾` with its session only by the first send (`/api/turn` with `fresh`), the
setup kept — leaving with `▴ done` before anything is sent leaves the conversations as they
were. A chat whose turn is running is joined instead, and a chat shown in another block of the
item is simply shown here too. An empty send
is refused (`type a message first`). While a turn of the item runs the line stays editable and
its message is never refused: it is queued. The editor's send, a retry
and the extraction marks still wait for the turn's end, refused with the notice `a turn of UID is
running — wait for it or stop it`.
