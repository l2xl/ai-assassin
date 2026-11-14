# Permission switches

The permission switches follow the setup pill on the same border: the harness's own tree
permission first, then the call modes the chosen connector lists in its settings (`modes`, each with
`id`, `label`, `hint`, `default` and `advanced`), then, while a browser extension is attached, the
harness's own Interactive WebSurf permission, off by default. A plain mode is a pill (`.chat-mode`,
`role="switch"`, titled `LABEL: HINT — allowed / not allowed in this chat, click to switch`, `.on`
and accent-coloured while allowed). The modes a connector marks advanced are not pills but the
entries of the `advanced ▾` drop-down (`.chat-advanced`, present only while the connector lists
such a mode, `.on` while any of them is allowed, titled with every entry's state): the menu lists
them as `role="menuitemcheckbox"` entries with `data-chat-mode`, `● Label` or `○ Label` titled by
the hint, one click switching the mode and closing the menu. The switched-on ones go with every
turn of the chat, the tree and Interactive WebSurf permissions to the harness, the rest to the connector. A
delegated turn has a harness permission on only while its parent's is on. Which permissions
there are, their defaults, what each allows and how a refused call reads are the children of the
permission switches item. Reading the tree — query and context — is the rail the harness runs on
and is never a permission, and neither is git, the project's change tracking carrier: its tool is
limited by its guard alone.

- **Advanced permissions** belong to their chat alone: they are never written to the settings and a new
  chat — a new conversation filed behind `▾` too — starts with them off.
- **A permission the connector does not list** (`Workflows` on an API connection) is ignored by the
  turns of the chat; it is no error and the switch keeps its state for a connector that lists it.
- **The check.** The permission list is read for every new chat from the `chat` section and for every
  turn from the chat's setup, and must be a list of permissions that exist. Otherwise it is replaced by
  the defaults at the source it was read from — the settings file, the chat's record — and a notice
  (`harness notice`, a message of the log) says what was wrong and what the list is now. The notice
  is part of the turn's text, so the AI is told what the user is shown.
