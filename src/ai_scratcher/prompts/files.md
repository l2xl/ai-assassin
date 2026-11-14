---
kind: tool
description: Browse the project's folders and read its files by line range, changing nothing
calls:
  list:
    optional:
      path: {type: string}
      depth: {type: integer}
  read:
    required: [path]
    optional:
      from: {type: integer}
      lines: {type: integer}
---
# Files
`{"tool": "list", "path": "src", "depth": 2}` lists a folder of the project — the root without `path`, one level without `depth` — a folder as its path with a trailing slash, a file as its path with its size in bytes.
`{"tool": "read", "path": "src/queue.py", "from": 120, "lines": 80}` returns the lines of a text file under their numbers, the whole file without `from` and `lines`; a long read is cut and tells the line to go on from.
- Both read only and are always allowed. Paths are relative to the project root; a path outside the project, in `.git`, under `syngate/` or naming the server's own settings and chat files is refused — the items are read through the tree calls.
- A file your context names by its path and size alone was too heavy to include: decide by the task whether to read it whole, read the part you need, or leave it.
- Read the lines you are about to patch before you patch them.
