# Patch tool

**Project files change through the patch tool** (`prompts/patch.md`, `patchlib`).
`{"tool": "patch", "diff": "--- a/GUIDE.md\n+++ b/GUIDE.md\n…"}` applies a unified diff to the
files of the project root with `git apply`, all of its sections or none, the paths it changed
coming back as the next prompt and a refusal carrying git's message for the section that failed.
The line counts of its hunk headers are set to the lines each hunk carries before git sees them, a
model miscounting them far more often than misquoting the context; a hunk ends at the next hunk
header or file header (a `--- ` line followed by a `+++ ` one), which git's own `--recount` would
read as a removed line. `{"tool": "replace", "path", "old", "new"}` changes the one occurrence of
an exact text in a project file — refused for a text absent or repeated there — so a change inside
a long line, a paragraph of prose or a table row, carries only the words that change, where a diff
repeats every whole line it touches with its context.
Its guard refuses a diff without a section, a file name without its `a/` or `b/` prefix, and a path
that is absolute, climbs out of the project (`..`), names `.git` or the tree (`syngate/`, a rename
into it included) or is a symbolic link: the items change only through the tree calls. The Edit
files permission is the harness's own, like Tree edit, on by default: while it is off a patch call
is refused (`project file edits are off for this chat — switch Edit files on`), the refusal going
back to the model as its next prompt.
