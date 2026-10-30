---
kind: skill
description: The format of the seed context a turn starts with and what it already includes
default: true
---
# Seed context
The seed context is the system prompt your turn starts with; it holds, in this order:
- the default prompt, every prompt text of the library under a `# Prompt <path>` line naming its file;
- the `# Tree features` section, the tree's `test: enabled|disabled` switch;
- the statements of the anchored item's ancestors, root first, its own and those of its descendants, each under its `@UID` line, an item a message names by `@UID` and the context lacks appended the same way;
- the project files those statements link, each under a `# Design <path>` line, its text in a four-backtick fence;
- the key source files the items list, each under a `# Source <path>` line, its text in a four-backtick fence, or `(file not found)`.
What the seed context includes is already read, as it stood when the turn started: do not open, grep or query again a prompt, an item statement, a design file or a source it holds. Read only what it lacks, or a file your own calls changed since.
