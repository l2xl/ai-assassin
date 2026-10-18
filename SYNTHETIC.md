# Synthetic AI harness core

Synthetic (`synthetic.py`) is the AI harness core of AI Assassin: the prompt library, the seed
context, the AI connections and the tool call protocol. It answers every exchange from the DAG rather than from a
transcript: a replica anchored at an item is answered above the item's seed context, and the reply
either continues the dialog or condenses it back into the DAG through tree calls.

## Seed context

The seed context of an item is the default prompt (`synthetic.PROMPTS["default"]`), then the tree's
test switch under `# Tree features` (`test: enabled|disabled`, read off the root item), then the seed
contexts of its parents in order, then its own statement, then those of all its children built
recursively in depth. Thus the seed context of the root is the whole DAG. The switch is what the
delivery skill (`deliver.md`) reads to tell a task that reworks items how to carry them into the
project: tests bound to the changed leaves first and the listed sources until the `test` call
passes when enabled, the listed sources alone — the need of a test rework being the turn's own
judgement — when disabled.

- **Every item enters once**, at its first occurrence, and the default prompt once at the head. The
  selection is the walk of `SYNGATE-010` (`syngatelib.walk(items, uid, descendants=True)`): the
  ancestors root first, then the item, then its descendants in sibling order, depth first. A parent
  brings its own ancestry, not its other children.
- **Every statement is addressable.** Each selected item enters as its own `@<UID>` line followed
  by its statement, a section opening with a blank line, so a message may name any contained item
  by `@UID`. A message referencing items the seed context already holds brings no second copy; only
  the missing ones are appended after it, each in the same `@<UID>` form.
- **Key sources close the context.** The `sources` of the selected items, each file once in
  selection order, follow as `# Source <path>` sections holding the file's text in a four-backtick
  fence; a missing file says so in place.

## Dialog tool

The reply line under an item's description opens an exchange anchored at that item; every replica
is one non-interactive turn of the chosen connector.

- **Context.** The seed context is the system prompt of the turn and the user's text is the prompt;
  every `@UID` the text names brings that item's statement in as one more section. Nothing else of
  the conversation travels except the connector's own session, which the next replica resumes; a
  turn without a session (text was folded out of or back into the exchange) carries the kept
  messages as a transcript heading the text. The Claude Code connector runs the local `claude` CLI
  with the call modes — each listed with its label, hint, default and whether it is advanced, for
  the page's permission switches — as its permission mode and allowed tools; its models and
  efforts are the ones the page offers. The Tree edit permission is the harness's
  own, on by default: while it is off a reply's add, edit, move and remove calls are refused
  (`tree edits are off for this chat — switch Tree edit on`), the refusal going back to the model as
  its next prompt; query, context, skill, test and agent stay allowed — reading the tree is the rail
  the harness runs on and is never switched off; a delegated child cannot switch it on while its
  parent's is off, and one line ahead of the user's text tells the model the tree is read-only for
  this chat, so it answers in text.
- **Prompt library.** The markdown files under the package's `prompts/` folder, by file stem
  (`synthetic.LIBRARY`), each opened by a front matter: `kind` — `skill` or `tool` — a
  `description` and, for a skill, `default`. A *tool* defines the format of a structured answer the
  harness turns into a call whose result reaches the model with the next turn; a *skill* is
  description only — the rules of calling tools (`call_tool.md`) and the rules of the DAG
  (`syngate.md`) are skills. The default prompt — deliberately not a `CLAUDE.md` — is composed from
  the library: the default skills, the list of the skills on request by name and description, then
  every tool definition. `{"tool": "skill", "name"}` brings a skill on request back as the next
  prompt, the way a query's result comes back.
- **Library delivery.** A connection declares `library_delivery`: `text`, the default prompt above
  merged into the seed context, or `native`, the connection processing the library through the
  provider's own skill and tool configuration, its dispatch receiving the library as an argument.
  A tool's front matter lists its `calls` — each with its `required` string fields and `optional`
  JSON-schema properties — so a tool added to the library needs no change of the connector. The
  Claude Code connector is `native`: the seed prompt carries the default skills and the item
  statements only; every skill on request is a `skills/<name>/SKILL.md` of a temporary plugin folder
  given with `--plugin-dir` (the `Skill` tool allowed for the turn); the calls of the tools make the
  JSON schema of the structured answer, the tools' texts its description.
- **One chat per item, several at once.** An item has exactly one chat, held by the server under
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
  is never stored as running — the chat of a removed item dropped with every conversation.
- **Two kinds of reply, never mixed.** A reply is **either** plain text — the dialog goes on — **or**
  exactly one list of Syngate API calls — the dialog is condensed into the DAG. The tools are handed
  to the turn as the JSON schema of its structured answer (`synthetic.ANSWER_SCHEMA`:
  `{"kind": "text", "text"}` or `{"kind": "calls", "calls": [...]}`; the Claude Code connector
  passes it as `--json-schema` and reads the turn's `structured_output`); a connector without
  structured output carries the same list in one fenced ```` ```syngate ```` block. A reply carrying
  both, or a malformed call, is refused (HTTP 422, shown as an error message in the chat whose
  retry mark sends the last message again; the session is kept, so the retry can ask for a clean
  answer).
- **Tree calls are the only way the agent touches the DAG.** The model never opens the files under
  `syngate/` — the Claude Code connector denies `Read`, `Edit` and `Write` under `syngate/**` in
  every mode, a shell command reading there refused the same way.
  `"@"` stands for the anchored item, every other item is addressed by its UID:
  `{"tool": "add", "uid", "parent" (default "@"), "description", "sources", "kind": "leaf"|"branch"}`
  adds a statement last among its parent's children, in the folder of its last sibling (else the
  parent's); `{"tool": "edit", "uid", "description", "sources"}` changes one, a given `sources` list
  replacing the item's; `{"tool": "remove", "uid"}` drops a childless statement;
  `{"tool": "move", "uid", "to", "before" (default last), "from"}` re-points the parent link and
  places the item, `from` naming the link when the item has several parents. The harness runs the
  calls in order through `add_item`, `edit_item`, `delete_item` and `move_item` and stops at the
  first refused one: the refusal goes back to the model as its next prompt with the results of the
  calls applied before it, so the model corrects the call or answers in text. The history shows
  every batch with what it applied, read or had refused; the reply lists what was applied, ran or
  was reported, never what was read; the user reviews the result as any other edit.
- **Queries read the DAG back the same way.** `{"tool": "query", "uid"}` returns the item's
  description, parents, sources, children in sibling order and kind; `{"tool": "context", "uid"}`
  its seed context; `{"tool": "skill", "name"}` the named skill. What a batch read goes back into
  the same session as the next prompt and the exchange continues with the next answer, for a
  bounded number of rounds (`synthetic.QUERY_ROUNDS`).
- **Test runs go through the page's runner.** `{"tool": "test", "uid", "name"}` runs the routines
  bound to the leaves under the item, `name` narrowing a leaf to one binding (the CLI spelling
  `syngate test UID:binding`); every `test` call of a batch joins one run after the batch's other
  calls. It is the same single-flight runner as `▶ Run test` — the records land in the run coverage, the
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
  rather than a spinner. The connector closes the turn with a `usage` step — `seconds`, `cost_usd`,
  `input_tokens`, `output_tokens` as the CLI's `result` event reports them — which the page folds
  into the activity header; the dispatch's `(reply, session)` shape stays as it is.
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
  collapsed transcript into that item's chat as an agent message once the turn ends — every `agent`
  step naming a known item other than the turn's anchor and its explicitly delegated children. Disk changes are the connector's
  own record: snapshots of the project files before and after the turn yield the `diff` step, the
  `Edit` / `Write` events its order.
- **Workflows are monolithic.** A `Workflow` tool call is one `workflow` step holding its input and
  result; the disk diff covers what it wrote; nothing is mirrored to children.
- **Stop is an emergency halt.** The chat's hide mark is a `■ stop` button while the turn runs
  (`POST /api/turn/<UID>:<n>/stop`); the user means "nothing more happens, from now", so the server
  acts in this order, the instant the request lands: the turn is marked stopped, which closes its
  gate — no tree call, test run or delegation of the turn is applied past that mark, a batch
  half-applied stays half-applied; the turns it delegated are stopped the same way; the test run it
  awaits is cancelled; and the connector is told to interrupt. Interrupting is cooperative first,
  so that the model's engine stops spending tokens on an answer nobody will read and the session
  stays resumable: the Claude Code connector runs `claude` with `--input-format stream-json`, the
  prompt going in as a user message, and sends the `{"type": "control_request", "request":
  {"subtype": "interrupt"}}` message on its stdin — the CLI aborts the API stream at once, records
  `[Request interrupted by user]` in the session and answers with an error `result`. A process that
  has not ended within a grace period (`claude_code_connector.grace` seconds) is killed with its
  whole process group, so the shell commands and subagents it started die with it. Either way the
  dispatch fails as a connection error; the steps collected and the calls applied before the stop
  stay, and the turn ends marked as stopped — a `stopped` message in the log, not an error. A stop
  that lands before the connector spawned its process spawns none.

The chat's place in the item panel, its ways of starting, the message tools and the history are
specified in [AI_CHAT.md](AI_CHAT.md).
