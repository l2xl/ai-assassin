# AI Assassin

A general-purpose AI assistant, built around deep iterative analysis of the
user–AI dialog and synthesis of its content into a **Synergy Context Gate (syngate)** — a DAG of
statements about the project of chat subject that then constructs the optimal context for the AI model,
per replica of the dialog.

AI Assassin is the synergy of three parts:

- **Syngate** (`syngatelib`, the `syngate` CLI, `render_syngate_report`, `check_self_approval`,
  [SYNGATE.md](SYNGATE.md)) — the subsystem managing the project's DAG, its test coverage and
  review status as a gate: open while everything passes, closed by anything failed.
- **Synthetic** (`synthetic`, [SYNTHETIC.md](SYNTHETIC.md)) — the AI harness core: the prompt
  library under `src/ai_scratcher/prompts/` — whose default skill
  [syngate.md](src/ai_scratcher/prompts/syngate.md) is the one statement of the rules the items
  follow — the seed context, the AI connections and the tool call protocol.
- **AI Assassin UI** (`assassin_ui`, the `assassin` command, [ASSASSIN_UI.md](ASSASSIN_UI.md),
  [AI_CHAT.md](AI_CHAT.md)) — the application joining both: the outline and document of the DAG
  with the AI chat anchored at every item.

A conversation with AI Assassin starts as an ordinary AI chat. Iteratively, the dialog is
transformed into a DAG: a sentence that survived the exchange becomes a node — a short
statement with the items it follows from as parents — and the chat goes on anchored at items rather
than at the tail of a transcript. The DAG is then the context engine: a replica anchored at an item
is answered from the item's seed context — the statements from the root down to the anchor and on
through everything under it, each once, in order — so the model receives exactly the reasoning that
leads to the point under discussion and what details it, not the whole history and not a lossy summary of it. The reply either continues the
dialog or condenses it back into the DAG, and the user keeps the last word by reviewing what the
DAG asserts.

Both directions of the loop are what the toolkit implements:

- **Dialog → DAG (analysis).** Items are plain text files — a YAML front matter of attributes over
  a markdown statement — shaped only by `parents` (*Tree Model* in [SYNGATE.md](SYNGATE.md)). The
  AI Assassin UI (`assassin`) shows the DAG as an outline and as one structured document, and the
  AI agent restructures it through *tree calls* — add, remove, move — never by editing files.
- **DAG → context (synthesis).** The seed context of an item is the chain of its ancestors'
  statements, root first, then its own, then those of all its descendants in depth, so the root's
  is the whole DAG; every item enters once at its first occurrence (`SYNGATE-010`). That selection,
  and only that selection, is what a replica anchored at the item is answered from
  ([SYNTHETIC.md](SYNTHETIC.md)).
- **Gate.** Two optional disciplines turn a DAG into a gate: *review* stamps an item as approved by
  the user, so the DAG cannot drift from what was agreed, and *test* binds an item to executable
  routines, so the DAG cannot drift from what the code does (*Process Rules* in
  [SYNGATE.md](SYNGATE.md)). Both are switched on the root item and are off by default.

Product architecture definition through AI dialog analysis and synthesis is one use case of this loop:
with `test` and `review` on, the DAG of a software project is its architecture and contract tree,
every leaf definition bound to a test frozen on approval, and an item's seed context is the context an AI coding
session is seeded from. Open Trader is such a project, and so is this repository — its own items
live under `syngate/` and its tests bind to them.

# Git

Git is the carrier of the project's change and evolution. Wherever the `git` command finds a work
tree around the project root, AI Assassin records the evolution of the DAG and of what it describes
as the project's history (`gitlib`); without one everything works as before, nothing of git offered.

- **The AI reads and records the history through the git tool**, never through raw shell commands:
  it reads anything, stages, commits and branches in every chat, no switch withholding it, and nothing
  it may call erases or rewrites what git holds; publishing stays the user's act ([SYNTHETIC.md](SYNTHETIC.md)).
- **Content commits are made with the AI.** The chat that made a change knows it best, so
  `⎇ Commit with AI` of the status popup asks the item's chat to commit the uncommitted changes, the
  AI condensing them into the message.
- **A review approves committed content and is committed itself.** `syngate review` refuses an item
  whose footprint — what its statement is built from — holds uncommitted changes
  ([SYNGATE.md](SYNGATE.md)), and the page's review commits the stamps it wrote, alone, right after:
  `Review: <subject>` of the one content commit it approves, or a message the AI formulates over
  several ([ASSASSIN_UI.md](ASSASSIN_UI.md)). The history thus alternates content commits and the
  review commits approving them, the two-commit re-approval the CI checks.

# Install and run

```
pipx install git+https://github.com/l2xl/ai-scratcher.git      # or: uv tool install git+…
cd <managed project>
assassin
```

The Python package is `ai_scratcher` (`syngatelib` library, `syngate` CLI, `assassin_ui`
application, `synthetic` harness, `check_self_approval`, `render_syngate_report`); any modern Python
(3.10+) with `pyyaml`, `jinja2` and `pytest` — pytest is a runtime dependency, not a dev extra:
`syngate test`/`review` run a managed project's pytest bindings with the toolkit's own interpreter.
Toolkit tests: `pip install -e .` then `pytest`.

**Managed project root**: `--root PATH` on any command, else the `SYNGATE_ROOT` environment
variable, else the nearest ancestor of the working directory holding a `syngate/` folder. `assassin`
falls back to the working directory itself and, on a project without any item file, bootstraps
`syngate/` with one root item named after the project ([ASSASSIN_UI.md](ASSASSIN_UI.md#the-server)). Test
discovery scans `scripts/tests/` and `tests/` for pytest bindings and `test/` for Catch2 ones.

# Contributing

AI Assassin manages its own tree: `syngate/` in this repository holds its requirement
items, bound to `tests/` through `@pytest.mark.syngate`. Develop against an editable install, so the
UI and CLI run the working copy rather than an installed snapshot:

```
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/assassin                    # http://127.0.0.1:<the project's own port above 8712>, tree = this checkout
```

`bin/assassin` does the same in one step: it creates `.venv` on first use (with `uv` when present,
else `python3 -m venv`), installs the checkout editable, and starts the UI with the arguments given.
`ASSASSIN_VENV` relocates the environment and `PYTHON` picks the interpreter.

```
bin/assassin --port 8712 --no-browser
```

`assassin` and `syngate` take the managed project from `--root`, else `SYNGATE_ROOT`, else the nearest
ancestor of the working directory holding `syngate/` — started from this checkout they edit this tree,
started from a managed project's checkout the same install edits that project's tree. The rest of the loop:

```
.venv/bin/syngate validate             # this tree: structural + frozen-routine checks
.venv/bin/syngate test 'ASSASSIN-UI-*' # bound routines of matching leaves, without stamping
.venv/bin/pytest                       # the whole test suite (tests/)
```

`review`/`clear` are user-only here as in any managed project. A managed project's own provisioning
(e.g. Open Trader's `<build dir>/ai-scratcher-venv`) also carries the `assassin` and `syngate` entry
points, so `<that venv>/bin/assassin` run from this checkout works too — against the fetched snapshot
of the package, not the working copy.
