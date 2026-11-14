# The content panel reads as one document

The right pane is one continuous text document. Item blocks follow each other as sections of it, shifted left by depth. Every block's label sits at the left end of its top border. The document fills the whole width the splitter leaves beside the outline, with no maximum of its own, its left margin narrower than its right one. A click on a block turns it into its description editor, as Enter does on the selected block or row; a click that ends a text selection leaves the rendered view as it is. `@UID` — and the older `[UID]` — of a known item, in a statement, a message or a file view, is a link that activates the item's block and unfolds the outline to it.

**Editing.** Each edited field is saved on its own as canonical YAML, the other fields untouched; an unknown parent, a parent cycle or a value changed on disk since it was loaded is refused. A save refused for a value changed on disk opens the conflict bar under the header, offering `keep mine`, which stores the typed text over the disk value, and `take theirs`, which drops the draft and shows the disk value. The header reads the state of the most pressing draft — unsaved, saving, `✓ saved` with its time, or failed with a click to retry — and the edited block carries the mark of its own statement. An edit of a reviewed item's statement, parents or bindings in the page drops its stamp and reverts its routine shas (the page always passes `--clear-review`); a change of its order alone leaves the review intact.

A block's border and all its border-mounted controls appear while the mouse pointer is over the block (or the keyboard focus is inside it) and disappear when it leaves; the revealed border is dim, the line colour or dimmer, never the accent or selection colour. The same applies to the controls of a sub-element: a message's tools, a file view's close button. A block whose chat or editor is open, or which is selected, keeps its controls shown while the border still follows the pointer — except the marks of a message, which come only with the pointer over that message's row — the full width of the pane at its height, past the border — or the focus inside it; on a device without hover every border and control is shown. Every control has an accessible name and is a `<button>`; the chat log is a live region; a block whose chat runs is `aria-busy`.

Below 60rem of viewport width the panes stack: the outline on top within 38vh of height, without a splitter and ignoring the remembered width; the document at full width with the depth shift halved; the filter spanning the header. Above it the outline opens at `clamp(18rem, 30vw, 40rem)` and the splitter resizes it (a double-click restores the default, arrows move it from the keyboard).

The chat strip on the block's bottom-left border is one pill whose glyph names its state: `✓ done` while the block is being edited (saves the statement and leaves the editor; Esc is its keyboard twin), `▴ done` while the chat is open and idle, `■ stop` (red) while a turn runs, `▾` on a block whose chat is hidden with history. Next to it, while editing, the save mark reads `● unsaved` / `saving…` / `✓ saved` / `✗ not saved — click to retry` / `⚠ conflict`.

## Sub-elements inside the item's content border

- **Files open inside the item.** A link to a file (`.filelink`) opens the file inside the block
  of the item that references it, the way the AI chat does: the block grows to hold the file
  view, the item's border (when revealed) enclosing description, chat and file alike. No separate
  file panel is placed next to or under the block. Only git-tracked files and markdown inside the
  project are served, and only markdown unchanged on disk since it was loaded is written: keys,
  coverage and chats sit untracked next to the tree.
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
