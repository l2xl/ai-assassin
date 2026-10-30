---
kind: tool
description: Change project files by a unified diff applied with git, whole sections at a time, never the syngate items
calls:
  patch:
    required: [diff]
---
# Patch
`{"tool": "patch", "diff": "--- a/GUIDE.md\n+++ b/GUIDE.md\n@@ -1 +1,2 @@\n # Guide\n+Read it.\n"}` applies a unified diff to the files of the project root, all of its sections or none; the paths it changed come back as your next prompt, or the refusal with git's message for the section that failed.
- Write each change as one semantically complete section, not as many small edits: a function, a paragraph, a whole block with its surrounding context lines of three. Do not split one change into a run of single-line hunks, and do not send the whole file when only a section moves.
- Use the common git form: `--- a/<path>` and `+++ b/<path>` names, `@@ -start,count +start,count @@` headers with the counts right, `/dev/null` for a file created or removed. Paths are relative to the project root and carry no leading slash.
- Paths under `syngate/` are refused, and so are `..`, `.git`, symbolic links and renames into syngate/: the items change only through the tree calls. The patch is the only way to change project files: Edit, MultiEdit, Write and NotebookEdit are not available to you.
- Read a file's current text before you patch it — the seed sources of the turn, or a query or skill result — since a context line that does not match the file refuses the whole diff.
- A patch that is refused changes nothing: correct the diff against the file as it is and send it again.
