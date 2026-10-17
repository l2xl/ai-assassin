# AI chat in the item panel

The chat is a part of the item's content panel rather than a window opened next to it. The item's
description is the first message of the exchange: it is shown once, as the content itself, since it
is already in the seed context, and the replies follow it inside the panel (`.block-chat` under
the description, the controls on the panel's bottom-left border, `.block-ai`).

## Starting a chat

- **By editing.** Editing the description starts a chat: the modified text is its first message.
  While the editor is open the AI controls appear on the bottom border as in a running chat —
  connector · model · effort (`.chat-setup`), the permission switches (`.chat-mode`), `➤ send`
  (`.chat-send`, titled `save the statement and send it as the first message of a new conversation —
  the previous one is kept, ▾ lists it (Ctrl/⌘+Enter)`) and `✓ done` (`.chat-done`, titled `done —
  the statement is saved, the editor closed (Esc)`) — so the setup can be chosen before the text is
  saved or sent. `➤ send` and Ctrl/⌘+Enter in the editor save the item and send the saved statement
  as the user's text of the first turn of a new conversation (`/api/turn` with `fresh`): the
  conversation so far is filed behind `▾`, nothing asked, nothing erased. While a turn of the item
  runs the send is refused with a notice (`a turn of UID is running — wait for it or stop it`), the
  editor staying open; an empty statement is refused the same way (`the statement is empty —
  nothing to send`). `✓ done` and Esc save the item and leave the editor; a chat the editor opened
  that holds no message hides with it, a chat with messages stays shown.
- **In the reply line.** Every panel holds the empty reply line (`.chat-input`) under its
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

  Entering the line — by click or by focus — opens the chat: the log and the controls appear, and
  a message sent from there starts the exchange without touching the item. When the item's chat
  holds messages and is shown nowhere in this tab, entering the line is the explicit choice of a
  new conversation (`update_chat` with `begin`): the log shown is empty, the previous conversation
  filed behind `▾` with its session, the setup kept; a chat whose turn is running is joined
  instead, and a chat shown in another block of the item is simply shown here too. An empty send
  is refused (`type a message first`). While a turn of the item runs the line stays editable, so
  the next message is prepared meanwhile, but its send is refused with a notice (`a turn of UID is
  running — wait for it or stop it`), the send pill dimmed and the typed text kept in the field.
- **Edit, then reply.** Clicking the reply line right after an edit saves the item, leaves the
  editor with the chat shown and waits for one more message before anything goes to the AI, so an
  edit never fires an exchange by itself.

## Setup and permissions

The setup pill (`.chat-setup`, titled `connector · model · effort — click to change`; with a single
connector it reads `model · effort ▾`, the connector named in its title) opens the menu choosing the connector, its model and the
efforts that model supports, and holds the three resets: `↺ New session` keeps the shown history and
drops the connector session, so the next turn starts a new one headed by the kept messages;
`＋ New chat` (`begin`) files the live conversation behind `▾` and leaves an empty one, unasked;
`✕ Delete chat` (`erase`) erases the live conversation's log and session after confirmation
(`Delete this chat of UID? Its N messages and session are erased.`), the filed ones untouched. All
three are refused while a turn runs.

The permission switches follow the setup pill on the same border: the harness's own tree
permission first, then the call modes the chosen connector lists in its settings (`modes`, each with
`id`, `label`, `hint`, `default` and `advanced`). A plain mode is a pill (`.chat-mode`,
`role="switch"`, titled `LABEL: HINT — allowed / not allowed in this chat, click to switch`, `.on`
and accent-coloured while allowed). The modes a connector marks advanced are not pills but the
entries of the `advanced ▾` drop-down (`.chat-advanced`, present only while the connector lists
such a mode, `.on` while any of them is allowed, titled with every entry's state): the menu lists
them as `role="menuitemcheckbox"` entries with `data-chat-mode`, `● Label` or `○ Label` titled by
the hint, one click switching the mode and closing the menu. The switched-on ones go with every
turn of the chat, the tree permission to the harness, the rest to the connector. Which permissions
there are, their defaults, what each allows and how a refused call reads are the children of the
permission switches item. Reading the tree — query and context — is the rail the harness runs on
and is never a permission.

## Messages

- **Styles.** A message is a full-width row of the log (`.chat-msg`) whose body (`.msg-body`) is
  the bubble: the user's (`.chat-msg.user`) styled as the description text, flush left on the panel
  background, shown as typed, not rendered; the AI's reply (`.chat-msg.ai`) shifted right and
  highlighted — the roles switch one body style, nothing more. A reply a delegated turn produced is
  headed `delegated by UID (turn n)` (`.msg-from`).
- **Marks.** Every message of the log — the content, shown once, carries none — has round buttons
  on the block's border lines (`.msg-tools`), revealed while the pointer is over the row — the
  full width of the pane at the row's height, past the border — or the focus is inside it, always shown on a device without hover, hidden while text in it is selected:
  - on the left line, level with the first line of every part of the text, a fold mark
    (`.msg-fold`, `aria-expanded`): it folds the part to its first line, grey (`.msg-cut`; a
    message folded whole is `.chat-msg.dropped`), and cuts it out of the exchange — folded text
    does not travel with the next turn — or expands a cut back into the text. The fold marks are
    frozen while a turn runs (`aria-disabled`, the server answering 409).
  - on the right line, the two marks that turn the kept text of the message into a syngate item:
    `↳` (`.msg-child`), level with the first line, adds it as a child of the anchored item, `↓`
    (`.msg-sibling`), level with the last line and pushed under the child on a message of a line or
    two, as its next sibling. Both go through the editor's own `add_item`; the text is the item's
    body, its first line thereby the title shown in the outline (a leading heading mark is
    stripped). The chat stays as it is after the transform: the new item is extracted from it, not
    replaced by it; a toast names the new UID and the outline flashes its row. A message folded
    whole carries no extraction marks.

  An error message (`.chat-msg.error`, a failed turn) carries on the right line instead `↻ retry`
  (`.msg-retry`), which sends the user's last message again in the same session without logging it
  twice, and `✕ remove` (`.msg-drop`), which drops the attempt from the log. A stopped turn's
  message (`.chat-msg.stopped`, dim, prefixed `■ stopped — `) carries the fold only; on either the
  fold is a reading aid, neither being in the exchange.
- **Selection marks.** While text inside a message is selected the message's own marks hide and
  the same three marks (`#sel-tools`) stand on the border lines level with the selection — the fold
  and child marks at its first line, the sibling mark at its last. The fold mark cuts the selected
  text out of the message: the cut is shown folded in its place, its own mark expanding it back;
  the selection is mapped onto the message's text by the alphanumerics shown, so the markup of a
  reply is stepped over. The extraction marks make the selected text alone a child or the next
  sibling item.
- **Items as references.** A chat message names an item the way a file is named with `@`: the
  harness resolves every `@UID` into the item's statement for the turn, appended to the seed
  context as one more section (`@UID`, then the statement), the message text staying as typed; in
  the rendered log `@UID` of a known item is a jump link, as `[UID]` is.
- **What travels.** A turn resumes the connector's session, so the exchange itself stays with the
  connector. Switching a fold mark drops the session: the next turn starts a new one, headed by
  the transcript of the kept text — the cuts taken out of every message, a message left empty left
  out — so folded text is really out and expanded text back in. No fold mark can be switched while
  a turn runs.

## Waiting and the turn's activity

While a turn runs — a single answer, or one with tool calls, subagents or a workflow — the log ends
with the turn's **activity header** (`.turn-activity`) growing live, and the `▴ hide` pill is a
`■ stop` button (`.chat-stop`, red, `AI_CHAT-STOP-BUTTON`; Ctrl/⌘+. is its keyboard twin): the chat
can be neither hidden nor its fold marks switched until the turn ends. One press turns it into
`stopping…`, disabled, until the outcome lands.
Stop is an emergency halt: nothing of the turn reaches the tree, the project or the model past it,
the connector being interrupted and the delegated turns stopped with it ([SYNTHETIC.md](SYNTHETIC.md),
*Turn*); the steps collected and the calls applied before the stop stay, and the log shows the turn
as stopped — a dim `■ stopped — ` message, not an error. The turn itself runs on the server as
`<UID>:<n>` of the item's chat ([SYNTHETIC.md](SYNTHETIC.md), *Turn*), so a reload of the page, or
any other page showing the item, re-attaches to it and shows its progress and reply when they come.
The outline mirrors the state: the row of an item that has a chat carries a chat state mark —
a spinner while a turn runs, a dot while a reply this tab has not shown waits, a warning when the
last turn failed, a dim mark for a hidden chat; a hidden chat's `▾` carries the spinner too.

- **Collapsed by default.** A finished turn is its answer under the activity header — `7 tool
  calls · 2 subagents · 3 files changed · 48 s · $0.12` — the wall time and, when the connector
  reports them, the cost and token counts close the header, which a turn without steps still shows
  as that one line; the step list under it is present only when the turn had steps beyond the
  answer and is collapsed at rest. Expanding it lists the steps as one-liners (`.turn-step`) in
  order, each expanding in turn: a tool call to its input and result, `reasoning` to the exposed
  text, `calls` to the tree calls of a batch (labelled `read` when every tool is a query, `applied`
  otherwise), a `diff` to its file list (`added` / `changed` / `deleted`), each file to its hunks,
  a `workflow` to its input and result, an `agent` step to a nested transcript rendered by these
  same rules.
- **Rules and shifts, never boxes.** The header sits on the reply's own bottom rule and the steps
  are shifted under it, as SYNGATE-UI.md prescribes for every sub-element.
- **Subagents reach their items.** A subagent anchored at a child item — explicitly, through the
  `agent` tool, or by the `@UID` convention of an implicit one — is also shown in that item's chat
  as an agent message with its collapsed transcript, an implicit one once the turn ends.

## History

An item has one chat, held by the server — stored in `syngate_chats.json` next to the tree,
untracked like the coverage file, so a restart keeps it — and shown as the same chat in every block
of the item and in every browser tab. The chat is its **live conversation** — the log, session and
setup the turns address — with the item's earlier conversations **filed** behind it, each with its
own log, session and setup, in start order; the page reads them as summaries (`archive`:
`started`, `title` — the first line of the first message — and `messages`). A conversation is
filed, never erased, by whatever begins a new one: the reply line entered on a hidden chat, the
editor's send, `＋ New chat`. A conversation without messages is not kept.

The `▴ hide` pill (`.chat-hide`, dim, never green, titled `hide the chat here — ▾ lists it again,
nothing is lost`) hides the chat in that block and becomes `▾` (`.chat-show`) on the bottom-left
border; while the editor is open the same place holds `✓ done`. `▾` is the way back to what was
said: it always opens the drop-down of the item's conversations, even when it holds a single one
(`conversations`, `data-chat-resume`, the live one first marked `●` unless it is empty, the filed
ones `○`, each `title · N messages · time` — the time of day for a conversation begun today, the
date before it otherwise), and nothing is shown until an entry is picked: picking one shows it, a
filed one resumes (`update_chat` with `resume`),
becoming the live conversation with its session and setup while the live one is filed in its place.
Resuming and beginning are refused while a turn runs (409). Hiding is refused with the toast
`send or clear the message first` while the reply line holds text. Esc does what the pill does: in
the editor and in the empty reply line it is the done mark; with text in the line it only returns
the focus to the block. The chat of an item removed from the tree is dropped with every conversation.
