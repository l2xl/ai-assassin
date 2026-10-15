# AI chat in the item panel

The chat is a part of the item's content panel rather than a window opened next to it. The item's
description is the first message of the exchange: it is shown once, as the content itself, since it
is already in the seed context, and the replies follow it inside the panel (`.block-chat` under
the description, the controls on the panel's bottom-left border, `.block-ai`).

## Starting a chat

- **By editing.** Editing the description starts a chat: the modified text is its first message.
  While the editor is open the AI controls appear on the bottom border as in a running chat —
  connector · model · effort (`.chat-setup`), the mode switches (`.chat-mode`) and `➤ send`
  (`.chat-send`) — so the setup can be chosen before the text is saved or sent. `➤ send` and
  Ctrl+Enter in the editor save the item and send the saved statement as the user's text of the
  first turn.
- **In the reply field.** Every panel holds the empty reply field (`.chat-input`) under its
  description at all times, with no button and no hint while at rest. Entering it — by click or by
  focus — opens the chat: the hint, the log and the controls appear, and typing there starts the
  exchange without touching the item.
- **Edit, then reply.** Clicking the reply field right after an edit saves the item and waits for
  one more message before anything goes to the AI, so an edit never fires an exchange by itself.

## Messages

- **Styles.** The user's messages (`.chat-msg.user`) are styled as the description text, left
  aligned on the panel background; the AI's replies (`.chat-msg.ai`) are aligned right and
  highlighted — the roles switch one message style, nothing more.
- **Tools.** Every reply but the first (the content) carries at its left edge, level with its
  first line (`.msg-tools`):
  - a collapse / expand button (`.msg-fold`, `aria-expanded`) folding the message to its first line;
  - a check mark (`.msg-keep`, `role="checkbox"`, on by default); switched off, the message is
    dropped from the exchange temporarily — its text turns grey (`.chat-msg.dropped`) and it does
    not travel with the next turn until switched on again;
  - two buttons that turn the message into a syngate item: `.msg-child` adds it as a child of
    the anchored item, `.msg-sibling` as its next sibling. Both go through the editor's own
    `add_item`; the message's text is the item's body, its first line thereby the title shown in
    the outline (a leading heading mark is stripped). The chat stays as it is after the transform:
    the new item is extracted from it, not replaced by it.
- **Items as references.** A chat message names an item the way a file is named with `@`: the
  harness resolves every `@UID` into the item's statement for the turn, appended to the seed
  context as one more section (`@UID`, then the statement), the message text staying as typed.
- **What travels.** A turn resumes the connector's session, so the exchange itself stays with the
  connector. Switching a check mark drops the session: the next turn starts a new one, headed by
  the transcript of the kept messages, so a dropped message is really out and a kept one back in.

## Waiting and the turn's activity

While a turn runs — a single answer, or one with tool calls, subagents or a workflow — the log ends
with the turn's **activity header** (`.turn-activity`) growing live, and the green check mark is a
`■ stop` button (`.chat-stop`, `AI-CHAT-CONTROLS-030`): the chat can be neither closed nor collapsed until the turn ends.
Stop is an emergency halt: nothing of the turn reaches the tree, the project or the model past it,
the connector being interrupted and the delegated turns stopped with it ([SYNTHETIC.md](SYNTHETIC.md),
*Turn*); the steps collected and the calls applied before the stop stay, and the log shows the turn
as stopped. The turn itself runs on the server as `<UID>:<n>` of the item's
chat ([SYNTHETIC.md](SYNTHETIC.md), *Turn*), so a reload of the page, or any other page showing
the item, re-attaches to it and shows its progress and reply when they come.

- **Collapsed by default.** A finished turn is its answer under the activity header — `7 tool
  calls · 2 subagents · 3 files changed · 48 s` — present only when the turn had steps beyond the
  answer and collapsed at rest. Expanding it lists the steps as one-liners (`.turn-step`) in order,
  each expanding in turn: a tool call to its input and result, `reasoning` to the exposed text, a
  `diff` to its file list, each file to its hunks, a `workflow` to its input and result, an `agent`
  step to a nested transcript rendered by these same rules.
- **Rules and shifts, never boxes.** The header sits on the reply's own bottom rule and the steps
  are shifted under it, as SYNGATE-UI.md prescribes for every sub-element.
- **Subagents reach their items.** A subagent anchored at a child item — explicitly, through the
  `agent` tool, or by the `@UID` convention of an implicit one — is also shown in that item's chat
  as an agent message with its collapsed transcript.

## History

An item has one chat, held by the server and shown as the same chat in every block of the item and
in every browser tab. The green check mark (`.chat-close`) hides the chat in that block and becomes
a drop-down icon (`.chat-reopen`, `▾`) on the bottom-left border that shows it there again, as does
entering the reply field. Only the editor's send starts the item's chat anew: the old chat's
messages and session are erased first, and the sent statement is the new chat's first message.
