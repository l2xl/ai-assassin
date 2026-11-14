# Git tool

**Git goes through the git tool** (`prompts/git.md`, `gitlib`), offered to a turn only while git
is at hand for the project — the `git` command found and the project root inside a work tree, read
once when the server starts; otherwise the library handed to the connector lacks it.
`{"tool": "git", "command": "log --oneline -5"}` carries the command line after `git`, split into
words the way a POSIX shell splits them — quotes and backslashes, no expansion — and never run by
a shell. It runs in the project root — or in the folder named by the optional `path`, see below — with `GIT_PAGER=cat`, `GIT_EDITOR=false`,
`GIT_TERMINAL_PROMPT=0` and no stdin, within a time limit; its exit status and output, cut past a
limit, go back as the next prompt the way a query's result does, so a failing command is the
model's to read rather than a refusal. The command line is the flexible part; the guard keeps it
from erasing what git holds — every accepted command either **reads** or **records** (adds to the
history, the index, the branches and the tags) and none discards, rewrites or deletes. Git being
the project's change tracking carrier, no permission switch gates the tool — the guard is its only
limit:
- reads: `status`, `diff`, `log`, `show`, `blame`, `grep`, `ls-files`, `shortlog`, `describe`,
  `rev-parse`;
- records: `add`, `commit`, `mv`, `rm`, `restore --staged`, `branch`, `tag`, `switch`, `merge`,
  `cherry-pick`, `revert`;
- every other command is refused, those rewriting or discarding among them (`reset`, `checkout`,
  `restore` of the work tree, `clean`, `rebase`, `stash`, `gc`, `prune`, `reflog`, `update-ref`,
  `filter-branch`, `config`) and those leaving the machine (`push`, `pull`, `fetch`, `remote`):
  the tool works on the local repository, publishing stays the user's act; so is an option ahead of
  the command (`-c`, `-C`, `--git-dir`, …) and an alias — the first word is a listed command;
- options refused on the listed commands, a long one in every abbreviation git accepts
  (`--amen`), a short one anywhere in a bundle (`-fr`) — so a value glued to its option may be
  refused too, the refusal asking for it as a word of its own; past `--` the words are paths:

  | command | refused options |
  |---|---|
  | `commit` | `--amend`, `--no-verify` / `-n` |
  | `add`, `mv` | `--force` / `-f` |
  | `rm` | `--force` / `-f`, `--pathspec-from-file` |
  | `branch` | `--delete` / `-d` / `-D`, `--move` / `-m` / `-M`, `-C`, `--force` / `-f` |
  | `tag` | `--delete` / `-d`, `--force` / `-f` |
  | `switch` | `--force-create` / `-C`, `--force` / `-f`, `--discard-changes`, `--merge` / `-m`, `--orphan` |
  | `merge`, `cherry-pick`, `revert` | `--abort` |
  | `restore` | every form but `--staged` without `--worktree` / `-W` |
  | any | `--output`, `--no-index`, `--open-files-in-pager` / `-O` |
- the tree stays the tree calls': `mv` and `rm` refuse a path under `syngate/` or holding it, and
  every glob or pathspec magic (`*`, `?`, `[`, a leading `:`) among their paths. Staging and
  committing an item changes nothing of it, and the reads are not filtered — the history of the
  items is what a commit message is formulated from; the tree files stay closed to the model's file
  tools only.

**A submodule is worked in through `path`.** From the project root a submodule is one opaque entry —
`status` shows it as modified, `diff` as a moved pointer, `add` of a file inside it fails — so
`{"tool": "git", "path": "libs/foo", "command": "status"}` runs the same command line, through the
same guard, with that folder as its working directory, the way `git -C` would; the option itself
stays refused ahead of the command. The path is a folder relative to the project root, and only the
root of a git work tree of its own is accepted — a submodule or a nested repository: an absolute
path, a `..` component, a folder resolving (symlinks followed) outside the project, a path in
`.git` or under `syngate/`, a missing folder and a folder inside the project's own
work tree but no root of one are refused, the last asking to leave `path` out and name the
files in the command. `.` stands for the project root. The `mv` and `rm` tree guard keeps judging
the paths of the command itself. The tool never publishes: a commit made inside a submodule leaves
the pointer of the project unrecorded until it is staged and committed in the project root as a
change of its own.

The tool's text tells the model how its commits read: what belongs to one change staged
together, the subject condensing it in the style of the log, never opening with `Review` — the
review commit's word — and review stamps never committed together with content.
