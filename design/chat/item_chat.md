# Item chat

**One chat per item, several at once.** An item has exactly one chat, held by the server under
the item's UID (`GET /api/chats`) and shown as the same chat wherever the item is shown — at every
occurrence of a multi-parent item and in every browser tab, each polling the server for changes.
Any number of items chat at the same time, each exchange running in parallel with the others, one
turn per item at a time. The chat is the item's live conversation; the earlier ones are filed
behind it with their logs, sessions and setups, and the `▾` mark of a hidden chat lists them —
even a single one — to pick from. A new conversation begins — the live one filed, never
erased — by the editor's send (`/api/turn` with `fresh`), by the reply line entered on a hidden
chat or by the page's new-chat action (`update_chat` with `begin`); a filed one resumes with its
session and setup (`update_chat` with `resume`), the live one filed in its place; `erase` deletes
the live conversation only, after the page's confirmation; a session reset without erasing is the
page's other reset (`update_chat` with `reset`), after which the next turn carries the kept
messages as its transcript. The chats live in `assassin_chats.json` next to the tree, outside git,
written on every settled change (a message appended, a setup or mark changed, a conversation
begun, resumed or erased, a reset) through a debounced writer and read at start — a running turn
is never stored as running — the chat of a removed item dropped with every conversation. A
renamed item keeps its chat: the chat and its latest turn follow the item to the new UID, and a
rename is refused (`409`) while the item's chat runs a turn other than the one renaming it.
