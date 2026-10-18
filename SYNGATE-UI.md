# Syngate UI guidelines

The browser UI is two panels: the outline tree on the left and the content panel on the right. The AI chat is part of the content panel: every item block holds the chat anchored at its item ([AI_CHAT.md](AI_CHAT.md)). Both panes draw every visual definition from one stylesheet, with a light and a dark scheme over the same tokens chosen by the system preference. The page's `<h1>` and `document.title` derive from the root item's first line (`<root title> · syngate`); the static title reads `syngate` until the model loads.

## The tree panel is the outline of the DAG

The DAG of syngate items is rendered as a tree: an item with several parents appears once under each of them, every row the same item. The tree doubles as the table of contents of the content panel. A row is the collapse mark or the leaf dot, the common item label, the chat state mark, the title and, at the right edge, the `⋯` menu (`⇑ Add parent`, `+ Add child`, `⊖ Unlink from P`, `✕ Delete item`); nothing else on the row acts in one click.

- **Drag and drop.** A row is dragged by its handle (icon and UID). The top and bottom quarters of a target row mean before and after it, the middle means under it; after an unfolded branch means first among its children; the root accepts only under. Holding the drop over a folded branch unfolds it after a moment; Ctrl at the drop adds the target as one more parent instead of moving. Alt+Shift+arrows are the keyboard twin. An item no root reaches is listed after the roots; a parent link that closes a cycle is shown once, marked `(cycle)`, and unfolds no further.
- **Menu.** `Add parent` is not offered on a root, `Unlink from P` only when the item has several parents, `Delete item` only on a childless item, after the confirm `Delete UID and its file PATH? This cannot be undone.`; the menu opens with its first entry focused, arrows move along it, Esc returns to the `⋯` button.
- **Filter.** The header's filter field (`/` focuses it; placeholder `Filter by UID or text (press /)`) and the three status chips (`N failed`, `N not run`, `N passed`, a chosen chip showing ` ×`) narrow both panes; the outline unfolds to every match and keeps an ancestor for a matching descendant; a move is refused while a filter is on.
- **Chat state.** The row carries a mark after the label only while the item has a chat: a spinner while a turn runs, a dot while a reply this tab has not shown waits, a warning when the last turn failed, a dim mark for a hidden chat; clicking it activates the block and shows the chat.
- **Keyboard.** Up and Down, PageUp and PageDown, Home and End move the selection in the pane holding the focus (the tree walks the folded outline, the document every item); Right and Left unfold and fold a row; Enter opens the editor; Esc is the done mark; Ctrl/⌘+Enter sends; Ctrl/⌘+. stops the turn; `m` on a focused block opens its row menu, `s` its status popup; `?` lists the keys. Tab moves between the filter, the selected row with its tools and the selected block: every border-mounted control and tool is a button in the Tab order, the reply line joining it only with the open chat or the editor.

## The common item label and the status popup

Wherever an item is shown — the row, the block's top border — its label is the composite status icon followed by the UID. The icon is one element: a circle filled by the test status (green passed, red failed, grey not run — the page's word for the `unknown` axis value), the review eyes `👀` over it for a standing stamp, the eyes with `❗` laid over their right part for a violated stamp, nothing for no stamp. The circle's diameter is about 1.15× the glyph font size plus 2px; the eyes sit shifted toward the circle's right edge so they still mostly overlap it, drawn from the colour emoji fonts (Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, Twemoji Mozilla). The icon is a button: clicking it in either pane opens the status popup — the status lines (a leaf's bindings with routine, frozen mark and last run; a branch's tally of the leaves below, each failing or not-run leaf a jump link; the item's validation problems, also shown inline in the block), the binding editor of a childless item, the test runs, then the run actions: `▶ Run test` / `▶ Run tests of N leaf items`, `👀 Mark reviewed` / `👀 Mark reviewed with N items below`, `✕ Clear review`. Nothing else on the page shows the status: no second pill on the block, no hover tooltip, no `T` button on the row. With both features off the icon stays, unfilled and without a glyph, since it anchors the run.

## The content panel reads as one document

The right pane is one continuous text document. Item blocks follow each other as sections of it, shifted left by depth. Every block's label sits at the left end of its top border.

A block's border and all its border-mounted controls appear while the mouse pointer is over the block (or the keyboard focus is inside it) and disappear when it leaves. The same applies to the controls of a sub-element: a message's tools, a file view's close button. A block whose chat or editor is open, or which is selected, keeps its controls shown while the border still follows the pointer — except the marks of a message, which come only with the pointer over that message's row — the full width of the pane at its height, past the border — or the focus inside it; on a device without hover every border and control is shown. Every control has an accessible name and is a `<button>`; the chat log is a live region; a block whose chat runs is `aria-busy`.

Below 60rem of viewport width the panes stack: the outline on top within 38vh of height, without a splitter and ignoring the remembered width; the document at full width with the depth shift halved; the filter spanning the header. Above it the outline opens at `clamp(18rem, 30vw, 40rem)` and the splitter resizes it (a double-click restores the default, arrows move it from the keyboard).

The chat strip on the block's bottom-left border is one pill whose glyph names its state: `✓ done` while the block is being edited (saves the statement and leaves the editor; Esc is its keyboard twin), `▴ done` while the chat is open and idle, `■ stop` (red) while a turn runs, `▾` on a block whose chat is hidden with history. Next to it, while editing, the save mark reads `● unsaved` / `saving…` / `✓ saved` / `✗ not saved — click to retry` / `⚠ conflict`.

## Sub-elements inside the item's content border

- **Files open inside the item.** A link to a file (`.filelink`) opens the file inside the block
  of the item that references it, the way the AI chat does: the block grows to hold the file
  view, the item's border (when revealed) enclosing description, chat and file alike. No separate
  file panel is placed next to or under the block. Only git-tracked files and markdown are served,
  and only markdown is written: keys, coverage and chats sit untracked next to the tree.
- **No nested rectangles.** A sub-element — a file view, a chat message, a tests section — is
  never drawn as its own bordered box. It is delimited by horizontal rules (`border-top` /
  `border-bottom`), by a left or right shift and by alignment: the user's messages flush left as
  the description, the AI's replies shifted right, a file view indented under its link. Fill may
  distinguish a sub-element; a full rectangle border may not.
- **Controls on lines, aligned to the sub-element.** The tool buttons and indicators of a
  sub-element sit either on its own bottom rule, or on the item's left or right border line,
  vertically level with the sub-element's first line (as the message marks stand on the block's
  border lines: the fold mark of every part of the text on the left line level with that part's
  first line, the child and sibling marks — or retry and remove on an error message — on the right
  line level with the message's first and last line, so the message text stays flush with the
  description). They are never floated inside the sub-element's text area, never given a box of
  their own, and no worded pill sits on a message's bottom rule.
- **Wording.** Pills, tooltips, toasts and states are lowercase; placeholders, menu entries and
  confirms sentence case; every count goes through `plural()`; shortcuts are written `Ctrl/⌘+Enter`.
  The chat and the console are *hidden* and *shown*, never *closed* — a file view, which is really
  removed from the block, is *closed*; `✓` means done, kept or saved, `👀` review; nothing shown to
  the user names a sha, a YAML key, a regex or an exception type.

## What the tab remembers

For the browser session only: the unfolded rows, the width of the outline and which blocks show their chat. The chats themselves — log, setup, connector session — are the server's, stored in `syngate_chats.json` next to the tree.
