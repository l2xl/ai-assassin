# AI Assassin UI guidelines

The AI Assassin browser UI, served by the `assassin` command (`src/ai_scratcher/assassin_ui.py` + `assassin_ui.html`), joins the syngate DAG of the project with the Synthetic AI harness. It is two panels: the outline tree on the left and the content panel on the right. The AI chat is part of the content panel: every item block holds the chat anchored at its item. Both panes draw every visual definition from one stylesheet, with a light and a dark scheme over the same tokens chosen by the system preference: colors, borders, backgrounds, buttons, pills and indicators come from it as custom properties and shared classes, with no inline style attribute inside the panes and no purpose-specific rule (send, test, review, hide, stop) redefining the shape a control's kind already has, so all border-mounted controls share one class and one look. The page's `<h1>` and `document.title` derive from the root item's first line (`<root title> · AI Assassin`); the static title reads `AI Assassin` until the model loads.

## What the tab remembers

For the browser session only: the unfolded rows, the width of the outline and which blocks show their chat. The chats themselves — log, setup, connector session — are the server's, stored in `assassin_chats.json` next to the tree.
