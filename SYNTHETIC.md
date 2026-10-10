# Synthetic AI-agent library

The synthetic agent (`synthetic.py`) answers every exchange from the DAG rather than from a
transcript: a replica anchored at an item is answered above the item's seed context, and the reply
either continues the dialog or condenses it back into the DAG through tree calls.

## Seed context

The seed context of an item is the default prompt (`synthetic.PROMPTS["default"]`), then the seed
contexts of its parents in order, then its own statement, then those of all its children built
recursively in depth. Thus the seed context of the root is the whole DAG.

- **Every item enters once**, at its first occurrence, and the default prompt once at the head. The
  selection is the walk of `SYNGATE-010` (`syngatelib.walk(items, uid, descendants=True)`): the
  ancestors root first, then the item, then its descendants in sibling order, depth first. A parent
  brings its own ancestry, not its other children.
- **Key sources close the context.** The `sources` of the selected items, each file once in
  selection order, follow as `# Source <path>` sections holding the file's text in a four-backtick
  fence; a missing file says so in place.

## Dialog tool

The reply line under an item's description opens an exchange anchored at that item; every replica
is one non-interactive turn of the chosen connector.

- **Context.** The seed context is the system prompt of the turn and the user's text is the prompt;
  every `@UID` the text names brings that item's statement in as one more section. Nothing else of
  the conversation travels except the connector's own session, which the next replica resumes; a
  turn without a session (a message was dropped from or restored to the exchange) carries the kept
  messages as a transcript heading the text. The Claude Code connector runs the local `claude` CLI
  with the call modes (edit, internet, workflows) as its permission mode and allowed tools; its
  models and efforts are the ones the page offers.
- **Prompt library.** The markdown files under the package's `prompts/` folder, by file stem
  (`synthetic.LIBRARY`), each opened by a front matter: `kind` — `skill` or `tool` — a
  `description` and, for a skill, `default`. A *tool* defines the format of a structured answer the
  harness turns into a call whose result reaches the model with the next turn; a *skill* is
  description only — the rules of calling tools (`call_tool.md`) and the rules of the DAG
  (`syngate.md`) are skills. The default prompt — deliberately not a `CLAUDE.md` — is composed from
  the library: the default skills, the list of the skills on request by name and description, then
  every tool definition. `{"tool": "skill", "name"}` brings a skill on request back as the next
  prompt, the way a query's result comes back.
- **One chat per item, several at once.** An item has exactly one chat, held by the server under
  the item's UID (`GET /api/chats`) and shown as the same chat wherever the item is shown — at every
  occurrence of a multi-parent item and in every browser tab, each polling the server for changes.
  Any number of items chat at the same time, each exchange running in parallel with the others, one
  turn per item at a time. A hidden chat keeps its history and session, and the `▾` mark shows it
  again; only the editor's send starts the item's chat anew, erasing the old one first.
- **Two kinds of reply, never mixed.** A reply is **either** plain text — the dialog goes on — **or**
  exactly one list of Syngate API calls — the dialog is condensed into the DAG. The tools are handed
  to the turn as the JSON schema of its structured answer (`synthetic.ANSWER_SCHEMA`:
  `{"kind": "text", "text"}` or `{"kind": "calls", "calls": [...]}`; the Claude Code connector
  passes it as `--json-schema` and reads the turn's `structured_output`); a connector without
  structured output carries the same list in one fenced ```` ```syngate ```` block. A reply carrying
  both, or a malformed call, is refused (HTTP 422, shown as an error in the chat; the session is
  kept, so the next replica can ask for a clean answer).
- **Tree calls are the only way the agent touches the DAG.** The model never edits the files under
  `syngate/` — the Claude Code connector denies `Edit`/`Write` under `syngate/**` in every mode.
  `"@"` stands for the anchored item, every other item is addressed by its UID:
  `{"tool": "add", "uid", "parent" (default "@"), "description", "sources", "kind": "leaf"|"branch"}`
  adds a statement last among its parent's children, in the folder of its last sibling (else the
  parent's); `{"tool": "edit", "uid", "description", "sources"}` changes one, a given `sources` list
  replacing the item's; `{"tool": "remove", "uid"}` drops a childless statement;
  `{"tool": "move", "uid", "to", "before" (default last), "from"}` re-points the parent link and
  places the item, `from` naming the link when the item has several parents. The harness runs the
  calls in order through `add_item`, `edit_item`, `delete_item` and `move_item`, stops at the first
  refused one and shows the applied list in the history; the user reviews the result as any other
  edit.
- **Queries read the DAG back the same way.** `{"tool": "query", "uid"}` returns the item's
  description, parents, sources, children in sibling order and kind; `{"tool": "context", "uid"}`
  its seed context; `{"tool": "skill", "name"}` the named skill. What a batch read goes back into
  the same session as the next prompt and the exchange continues with the next answer, for a
  bounded number of rounds (`synthetic.QUERY_ROUNDS`).
- **Test runs go through the page's runner.** `{"tool": "test", "uid", "name"}` runs the routines
  bound to the leaves under the item, `name` narrowing a leaf to one binding (the CLI spelling
  `syngate test UID:binding`); every `test` call of a batch joins one run after the batch's other
  calls. It is the same single-flight runner as ▶ run — the records land in the run coverage, the
  statuses recolor, a run live elsewhere refuses the call — and its outcome comes back like a
  query's result: one line per leaf binding with pass/fail, then the output of every failed routine.
  Review stamping stays the user's act: there is no review call.

## Turn

A turn is a server-side job of the item's chat, addressed as `<UID>:<n>` (`POST /api/turn` starts
it and refuses a second turn of the same item, `GET /api/turn/<UID>:<n>?wait=<s>` awaits it,
`POST /api/chat` is the same exchange awaited in one request). It lasts until the connector's
process exits, and its reply lands in the chat the server holds, so every page showing the item
picks it up, a reloaded one included; while any turn runs a page keeps one long poll out for the
next change of the chats (`GET /api/chats?since=<version>&wait=<s>`), one connection however many
chats are open. A turn is a tree of steps closed by an answer, never the answer alone:

- **Steps.** `message` (an intermediate answer of the model), `reasoning` (its exposed thinking), `tool` (name, input, result, duration),
  `calls` (the syngate calls applied), `diff` (the files the turn changed, with hunks), `agent` (a
  subagent: its prompt, the item it is anchored at if any, its own steps and its final report) and
  `workflow` (opaque: input and result). The connector streams every event into the turn as it
  happens, and each appended step bumps the chats version, so the pages render the progress live
  rather than a spinner.
- **Reasoning is requested whenever it may be had.** The harness always asks the connection to
  expose the model's reasoning when the call mode allows it, and records it only when it comes. For
  the Claude Code connector that depends on the model and the effort — a model without effort
  levels, Haiku 4.5 among them, has none to expose — so `reasoning` steps are optional in every
  transcript, never promised.
- **Explicit delegation, harness-controlled.** `{"tool": "agent", "uid", "prompt", "model",
  "effort", "modes"}` runs a turn of the named item's chat, anchored there with that item's own seed
  context. Every `agent` call of a batch runs in parallel after the batch's other calls, the parent
  turn awaits them, and their final reports come back as the next prompt the way query results do;
  a busy item refuses the call, since an item runs one turn at a time. The subagent is an ordinary
  turn of the child's chat, so its whole transcript is where the child is shown. The delegation
  skill, a default one, tells the model to analyse the scope of an item with children — reading them
  with `query` — and to delegate the separable ones this way. This is the preferred form.
- **Implicit subagents, observed.** Subagents the model launches inside its own session are
  observed, not steered. The Claude Code connector runs `claude` with
  `--output-format stream-json --verbose`, so every message, tool call and result arrives as an
  event, a subagent's launch with its prompt and its final report among them; after the turn the
  connector reads the session's transcript files for the subagents' own turns and attaches them to
  the `agent` steps. The delegation skill asks the model to open every subagent prompt with its
  target item (`@UID` on the first line), and the harness mirrors such a subagent's report and
  collapsed transcript into that item's chat as an agent message. Disk changes are the connector's
  own record: snapshots of the project files before and after the turn yield the `diff` step, the
  `Edit` / `Write` events its order.
- **Workflows are monolithic.** A `Workflow` tool call is one `workflow` step holding its input and
  result; the disk diff covers what it wrote; nothing is mirrored to children.
- **Stop keeps the steps.** The chat's close mark is a `■ stop` button while the turn runs
  (`POST /api/turn/<UID>:<n>/stop`), killing the connector's process: the steps collected and the
  calls applied stay, and the turn ends marked as stopped.

The chat's place in the item panel, its ways of starting, the message tools and the history are
specified in [AI_CHAT.md](AI_CHAT.md).
