# Seed context

The seed context of an item is the default prompt (`synthetic.PROMPTS["default"]`), then the tree's
test switch under `# Tree features` (`test: enabled|disabled`, as the switches set it for the anchored item), then the seed
contexts of its parents in order, then its own statement, then those of all its children built
recursively in depth. Thus the seed context of the root is the whole DAG. The switch is what the
delivery skill (`deliver.md`) reads to tell a task that reworks items how to carry them into the
project: tests bound to the changed leaves first and the listed sources until the `test` call
passes when enabled, the listed sources alone — the need of a test rework being the turn's own
judgement — when disabled.

- **Every item enters once**, at its first occurrence, and the default prompt once at the head. The
  selection is the item selection walk (`syngatelib.walk(items, uid, descendants=True)`): the
  ancestors root first, then the item, then its descendants in sibling order, depth first. A parent
  brings its own ancestry, not its other children.
- **Every statement is addressable.** Each selected item enters as its own `@<UID>` line followed
  by its statement, a section opening with a blank line, so a message may name any contained item
  by `@UID`. The item the context is formed for — the active item of the exchange — has its line marked `@<UID> (active item)`, the one statement so marked; a `context` call may name another one-line `label` for it, and the statements appended for a message's references carry no mark. A message referencing items the seed context already holds brings no second copy; only
  the missing ones are appended after it, each in the same `@<UID>` form.
- **Linked design files follow the statements.** Every project file the selected statements link,
  each once and none a key source already lists, follows them as a `# Design <path>` section holding
  its text in a four-backtick fence; a linked file that does not exist is left out.
- **Key sources close the context.** The `sources` of the selected items, each file once in
  selection order, follow as `# Source <path>` sections holding the file's text in a four-backtick
  fence; a missing file says so in place.
