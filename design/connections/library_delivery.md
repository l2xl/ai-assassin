# Library delivery

**Library delivery.** A connection declares `library_delivery`: `text`, the default prompt
merged into the seed context, or `native`, the connection processing the library through the
provider's own skill and tool configuration; the dispatch of a connection declaring either receives
the library as an argument — a `text` one building its answer schema from it.
A tool's front matter lists its `calls` — each with its `required` string fields and `optional`
JSON-schema properties — so a tool added to the library needs no change of the connector. The
Claude Code connector is `native`: the seed prompt carries the default skills and the item
statements only; every skill on request is a `skills/<name>/SKILL.md` of a temporary plugin folder
given with `--plugin-dir` (the `Skill` tool allowed for the turn); the calls of the tools make the
JSON schema of the structured answer, the tools' texts its description.
