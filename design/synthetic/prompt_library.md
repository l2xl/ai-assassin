# Prompt library

**Prompt library.** The markdown files under the package's `prompts/` folder, by file stem
(`synthetic.LIBRARY`), read from the files anew whenever a prompt is needed — every round of every turn, a skill call, the
default prompt, the answer schema — and never kept between two reads: `LIBRARY`, `SKILLS`, `PROMPTS` and `ANSWER_SCHEMA` are live
views that build themselves from the files at every access, a turn taking one consistent read of them per round. Each file is opened by a front matter: `kind` — `skill`, `tool` or `agent` ([agents.md](agents.md)) — a
`description`, `default` and, for a skill, `delivery`. A default skill heads the default prompt; a default tool —
the read-only grep tool — is the one tool an off-context agent has without listing it, a verdict agent
aside ([agents.md](agents.md)). A *tool* defines the format of a structured answer the
harness turns into a call whose result reaches the model with the next turn; a *skill* is
description only — the round of calling tools (`call_tool.md`, with `call_tool_text.md` and `call_tool_structured.md`), the rules of the DAG
(`syngate.md`) and the format of the reply (`reply.md`: the lead first, a long or secondary list —
tests run, items reworded, files changed — written as a collapsed `<details>` section the chat
shows folded to its summary) are skills. The default prompt — deliberately not a `CLAUDE.md` — is composed from
the library: the default skills, the list of the skills on request by name and description, then
every tool definition. `{"tool": "skill", "name"}` brings a skill on request back as the next
prompt, the way a query's result comes back.

**Skill delivery.** A skill naming a `delivery` — `text` or `native`, the library delivery a
connection declares — enters a system prompt only on a connection of that delivery, as a default
skill or by an agent's lists alike; a skill naming none enters on every connection. It keeps
what only one carrier of the answer needs out of the other's prompt: `call_tool.md` states the round
every connection runs and no carrier, `call_tool_text.md` (`text`) the answer object written as the
message content or its plain form with a fenced block, and `call_tool_structured.md` (`native`) the
answer tool ([answer.md](answer.md)).
