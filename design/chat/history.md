# History

An item has one chat, held by the server — stored in `assassin_chats.json` next to the tree,
untracked like the coverage file, so a restart keeps it — and shown as the same chat in every block
of the item and in every browser tab. The chat is its **live conversation** — the log, session and
setup the turns address — with the item's earlier conversations **filed** behind it, each with its
own log, session and setup, in start order; the page reads them as summaries (`archive`:
`started`, `title` — the first line of the first message — and `messages`). A conversation is
filed, never erased, by whatever begins a new one: the first send of a new conversation shown
by the reply line or the editor on a hidden chat, `＋ New chat`. A conversation without messages
is not kept.

The `▴ done` pill (`.chat-hide`, dim, never green, titled `hide the chat here — ▾ lists it again,
nothing is lost`) is the only state pill besides `■ stop`: it closes whatever is open in the block —
the editor, its statement saved, and the chat — and becomes `▾` (`.chat-show`) on the bottom-left
border. Text left in the reply line is kept by the tab, in memory, and is back in the line when
the item's chat shows again. `▾` is the way back to what was
said: it always opens the drop-down of the item's conversations, even when it holds a single one
(`conversations`, `data-chat-resume`, the live one first marked `●` unless it is empty, the filed
ones `○`, each `title · N messages · time` — the time of day for a conversation begun today, the
date before it otherwise), and nothing is shown until an entry is picked: picking one shows it, a
filed one resumes (`update_chat` with `resume`),
becoming the live conversation with its session and setup while the live one is filed in its place.
Resuming and beginning are refused while a turn runs (409). Esc does what the pill does, in the
editor, in the reply line and on the focused block; while a turn runs it only returns the focus to
the block. The chat of an item removed from the tree is dropped with every conversation.
