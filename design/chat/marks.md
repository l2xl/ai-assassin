# Message marks

**Marks.** Every message of the log — the content, shown once, carries none — has round buttons
on the block's border lines (`.msg-tools`), revealed while the pointer is over the row — the
full width of the pane at the row's height, past the border — or the focus is inside it, always shown on a device without hover, hidden while text in it is selected:
- on the left line, level with the first line of every part of the text, a fold mark
  (`.msg-fold`, `aria-expanded`): it folds the part to its first line, grey (`.msg-cut`; a
  message folded whole is `.chat-msg.dropped`), and cuts it out of the exchange — folded text
  does not travel with the next turn — or expands a cut back into the text. The fold marks are
  frozen while a turn runs (`aria-disabled`, the server answering 409).
- on the right line, the two marks that turn the kept text of the message into a syngate item:
  `↳` (`.msg-child`), level with the first line, as a child of the anchored item, `↓`
  (`.msg-sibling`), level with the last line and pushed under the child on a message of a line or
  two, as its next sibling. Neither writes the item itself: the mark sends the text as a new turn
  of the anchored item's chat, headed by the request to make it that child or sibling and to
  carry the new item's task on in its own chat. The AI words the statement by the DAG rules,
  names it with a semantic UID — never a numbered suggestion of the page — adds it and hands the
  task on through an `agent` call, the task routing skill of the prompt library telling it how; the new item's chat then shows the delegated
  turn. While a turn of the chat runs the send is refused with a notice, as a typed message is.
  A message folded whole carries no extraction marks.

An error message (`.chat-msg.error`, a failed turn) carries on the right line instead `↻ retry`
(`.msg-retry`), which sends the user's last message again in the same session without logging it
twice, and `✕ remove` (`.msg-drop`), which drops the attempt from the log. A stopped turn's
message (`.chat-msg.stopped`, dim, prefixed `■ stopped — `) carries the fold only; on either the
fold is a reading aid, neither being in the exchange.

**Selection marks.** While text inside a message is selected the message's own marks hide and
the same three marks (`#sel-tools`) stand on the border lines level with the selection — the fold
and child marks at its first line, the sibling mark at its last. The fold mark cuts the selected
text out of the message: the cut is shown folded in its place, its own mark expanding it back;
the selection is mapped onto the message's text by the alphanumerics shown, so the markup of a
reply is stepped over. The extraction marks send the selected text alone, as the message's own
marks send its kept text.

**What travels.** A turn resumes the connector's session, so the exchange itself stays with the
connector. Switching a fold mark drops the session: the next turn starts a new one, headed by
the transcript of the kept text — the cuts taken out of every message, a message left empty left
out — so folded text is really out and expanded text back in. No fold mark can be switched while
a turn runs.
