# Tool execution

A tool is seen from four sides, and the tree keeps them apart:

- **Execution** — the harness's one way to run a tool: every call an
  answer carries is executed by one implementation, the same whichever AI connection carried the
  answer. Each concrete tool — git, files, patch, shell, WebSurf and the others — is an item here.
- **Definition** — the prompt library's common
  format describing a tool or a skill to the AI. Every tool item is a child of the library's tool
  definition as well as of execution: one item, its prompt and its implementation.
- **A component of its own** — a tool too large for one item is a top-level branch of the project
  linked under its tool item: the browser extension under the WebSurf tool.
- **A connection's override** — a connection that configures skills and tools its own way states
  it in items of its own, linked under what they override: Claude Code's native delivery under
  the library's skill and tool definitions, its own tools denied or permitted under the tool
  they stand in for.

| tool | calls | implementation | gated by |
|---|---|---|---|
| Syngate API | `query`, `context`, `add`, `edit`, `move`, `rename`, `remove`, `test` | `synthetic.py`, `syngatelib.py` | Tree edit, for the changing calls |
| files | `list`, `read` | `filelib.py` | nothing — reads are always allowed |
| patch | `patch`, `replace` | `patchlib.py` | Edit files |
| git | `git` | `gitlib.py` | nothing; its guard refuses what erases |
| shell | `shell` | `assassin_ui.py` | Raw command |
| WebSurf | `websurf` | `websurf.py` | Interactive WebSurf, for `fill` and `mouse` |
| agent | `agent` | `assassin_ui.py` | the starting chat's permissions |
| skill | `skill` | `synthetic.py` | nothing |
| log | `log` | `loglib.py` | nothing — reads the chat's own record |
| setup | `models`, `setup` | `synthetic.py`, `assassin_ui.py` | nothing — it reads and recommends |

A connection that brings tools of its own is the exception, and its item hangs under the tool it
stands in for or switches off: the Claude Code connector's own `Bash` under the shell tool, its
denied edit tools under the patch tool, its denied `Agent` under the agent tool, its denied reads
of the tree under the files tool.
