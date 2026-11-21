# AI chat in the item panel

The chat is a part of the item's content panel rather than a window opened next to it. The item's
description is the first message of the exchange: it is shown once, as the content itself, since it
is already in the seed context, and the replies follow it inside the panel (`.block-chat` under
the description, the controls on the panel's bottom-left border, `.block-ai`).

## Starting a chat

- **By editing.** The page draws no line between editing the item and chatting about it: the
  editor and the chat are one interaction with one `▴ done`. Entering the editor shows the chat
  with the AI controls on the bottom border — connector · model · effort (`.chat-setup`), the
  permission switches (`.chat-mode`) — so the setup can be chosen before anything is sent; the
  statement is sent by Ctrl/⌘+Enter, the strip holding no send pill while it is edited. Which
  conversation it shows depends on whether a chat is active in the block:

  | Before the edit | The editor shows | Ctrl/⌘+Enter | `▴ done` / Esc |
  |---|---|---|---|
  | no chat shown — none yet, or a hidden one | a new, empty conversation | the saved statement as the first message of a new conversation (`/api/turn` with `statement`, `fresh` when a live one holds messages): the old one is filed behind `▾`, nothing asked, nothing erased | saves the item and closes editor and chat; no conversation is begun, filed or sent |
  | the chat shown in the block | that conversation | the saved statement announced into it | saves the item and closes editor and chat; the history stays, the change is announced with the next turn |

  The send goes whether the statement changed or not. While a turn of the item runs the send is
  refused with a notice (`a turn of UID is running — wait for it or stop it`), the editor staying
  open, and the stop pill stands in place of `▴ done`, so Esc ends the edit only; an empty
  statement is refused the same way (`the statement is empty — nothing to send`). Editing alone
  never sends anything.

- **Edit, then reply.** Clicking the reply line right after an edit saves the item, leaves the
  editor with the chat shown and waits for one more message before anything goes to the AI, so an
  edit never fires an exchange by itself.

## Subagents in the chat

- **Subagents reach their items.** A subagent anchored at a child item — explicitly, through the
  `agent` tool, or by the `@UID` convention of an implicit one — is also shown in that item's chat
  as an agent message with its transcript, an implicit one once the turn ends.
- **Running subagents are links.** Every subagent still running on a known item other than the
  chat's own — an agent step without report in the live activity, or a background one — shows as
  an indicator `.agent-run` (spinner and `@UID`) closing the activity; it is a link that jumps to
  that item's block, and so is the `@UID` of an agent step's line.
- **Background subagents leave the chat free.** An `agent` call marked `background` does not hold
  the parent turn: once the turn ends, the chat shows no `■ stop`
  and sends, while a header `N background subagents running` with
  the indicators stays under the log. A background subagent is stopped in its own item's chat; the
  server lists the running ones as `agents` of the chat. The report of one that ended joins the
  log as an agent message `report of @UID` with its transcript.

## Interruption

**Interruption.** An unexpected error of the harness ends the turn with a message saying the chat
was interrupted by a bug, not a refusal. A malformed answer of the AI is no such error: it is
refused to the AI as its next prompt, naming what is wrong, within the rounds of the turn.
