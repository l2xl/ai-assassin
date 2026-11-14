# The engine updates on the fly

Whatever part of the engine changes — by the AI's own turn, an IDE, git or a reinstall — it is picked up without a manual restart:

- **Prompts** are read from `prompts/*.md` whenever one is needed, so the next turn carries the edit.
- **The page** is read from `assassin_ui.html` for every `GET /`, stamped with its version (`data-page` on the root element, the first
  16 hex digits of its sha256); the fingerprint the page polls names the version served now. A tab seeing another one reloads itself
  as soon as it is idle — no unsaved edit, no open editor, menu, popup or mention hint, no drag, no selected text, no text in the field
  holding the focus — keeping in the session storage, beyond what it always keeps, the selection, the filters, the open file views, the
  unfolded steps, the text of every reply line (back in the line when its chat shows) and the scroll of both panes. A busy tab shows
  `⟳ page updated` in the header, which reloads it on click, and reloads by itself once idle.
- **The server's Python sources** — the `*.py` files of the package — are watched every second. A change, or a `restart now`, first
  compiles every source and imports the server in a fresh interpreter, once per state of the files; a failure keeps the running engine
  and the header reads `⛔ engine update does not load`, the error in its tooltip. Otherwise the restart waits until no turn, background
  subagent or run is live — the header reads `⟳ engine update waits for N running turns and runs` with `restart now`, which stops them
  first — then refuses any new turn or run (`503`), writes the chats out and re-executes the server in place (`os.execve`, same argv,
  `--no-browser`). The session token and the listening socket pass to the new process through `ASSASSIN_TOKEN` and
  `ASSASSIN_LISTEN_FD`, which it clears from its environment, so the URL keeps working and no request meets a closed port. Every run
  of the server has its own `boot` id in the model and the fingerprint; a page seeing a new one reads the tree and the chats anew, the
  chats version counting from zero again. `--no-reload` switches the watch off. A change of `pyproject.toml` still needs a restart
  through `bin/assassin`.
- **The tree and the opened files** are re-read by the page within a couple of seconds of any change on disk — an item file, a
  coverage file or an opened project file, changed by the agent's tree calls, git, an IDE or another tab — the selection, the open
  editor, the shown chats and the typed drafts surviving the re-read.
