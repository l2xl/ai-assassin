# Agents

Work that needs no item context — commit the changes, run the tests, search the files, judge a
text — is an **off-context agent**, *agent* for short here: a prompt of the library with
`kind: agent`, beside the skills and the tools.

```
---
kind: agent
description: Commit the uncommitted changes
examples: [commit the changes, commit the changes with message, commit all the changes related to]
tools: [git]
skills: [call_tool, call_tool_answer, call_tool_block]
---
```

- **The prompt is the whole system prompt**, with nothing of a seed context above it.
- **`tools` and `skills`** are the agent's fixed lists: the tools and the skills it has, and no
  others. The chat that starts it never adds to them or takes from them. Tools and skills follow
  the same two steps:
  1. *list* — the names of the key, in its order and each once; an agent without the key has
     none;
  2. *entry* — the prompts of the lists, skills then tools, are added to the system prompt after
     the agent's own text. No other prompt enters, a default skill included.

  A call of a tool outside the tool list is refused. A listed skill naming a `delivery` enters
  only on a connection of it, as the prompt library states.
- **The starting chat covers the lists.** An agent names no `modes` and never runs with less than
  its lists: what the chat that starts it must have, and what happens where it lacks it, is the
  cover of the run in [subagents.md](subagents.md).
- **Connection and model** are not the prompt's: the settings give every agent a model locator — `agents` of the
  `orchestrator` section, a default and an entry by name — pointing to
  a model of any configured connection, so the same agent is served locally or by a provider.
- **`examples`** are the phrasings the orchestrator's agent match shortlists the agent by; an agent without them is never matched from a message.

The agents shipped (least but not last):

- **commit** — reads `git status` and `git diff` and commits what belongs together under a one-line
  subject in the style of the log, without a body; the guard of the git tool is its limit.
- **test** — `tools: [syngate_api]`: its start message names the item UIDs, and it runs the
  routines bound under each through the tree's `test` call and reports the failed ones with
  their output. Its `tools` list gives it the tree calls and nothing else — no file change, no
  shell.
- **explore** — searches the project files for what the start message asks and reports the places
  found; it changes nothing. It stands in for the search subagents a connector would launch itself.

## Verdict agents

An agent whose front matter declares an answer `schema` — and then neither `tools` nor `skills` —
is a **verdict agent**: it is offered no tools, its answer is the JSON of that schema, and the harness reads it — it is never a reply of the
chat. What it is given to judge goes in as fenced data. The orchestrator's judgements are these
agents, each given by the settings a model locator of its own:

- **match** — which of the shortlisted agents a message asks for, or none;
- **prune** — for every AI text of an ended turn, whether it states something the session lacks;
- **scan** — the findings in external text: each a span, a category and a reason.

An agent's item states what its prompt holds — its tools, its skills, its schema, what it is told — since
that is what a test can assert; what a model then does with it is not a statement of the tree.
