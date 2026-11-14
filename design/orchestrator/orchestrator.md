# Orchestrator

The Orchestrator is the part of Synthetic that decides, for every
turn, **which agent answers it, above which context, with which model and permissions, and what of
it stays in the session**. Synthetic carries — prompt library, seed context, connections, tool
execution, and the subagents every session is one of; the
Orchestrator chooses what is carried. It exists because the seed context of a grown project is far
larger than any one message needs, and because a session fills with text that adds nothing to it.

The design assumes **a harness that owns everything**: the model is reached by plain API calls,
the session is a message list the harness writes, and every tool is the harness's own. A connector that owns part of this is an exception, stated once with that connector and nowhere else.

**Status.** Every step below is implemented and stated by items whose tests are bound and pass.
What stays open: the Claude Code connector keeps the exceptions of
[claude_code_orchestrator.md](../connections/claude_code_orchestrator.md) — its own `Bash` and web tools
unheld, its session never rewritten — and a new session is composed of the kept message texts
alone, so the steps no verdict pruned, a first file read among them, do not reach it.

Two words are kept apart throughout. A **conversation** is what the user sees: the log of a chat
since its last reset. A **session** is what a model is sent: the system prompt and the message
list of one connection and model; a conversation starts a new session when it is reset, when a
fold is changed by hand, and when its setup moves to another connection or model.

Measured on this repository (245 items): all statements together are about 10k tokens, the source
files about 80% of a seed context and the design files about 20%; the median item's seed context
is about 43k tokens and the root's about 194k, two files (`assassin_ui.html`, `assassin_ui.py`)
making 72k of it. The lever is therefore the files: **the graph of items is always complete** —
every item of a seed context with its whole statement — and what is cut is the content of a heavy file,
down to its reference, and a technical message out of the session.

## The path of a turn

1. **Services.** The model services are configured and answering, or the chat is blocked.
2. **Agent match.** A message that asks for an off-context agent runs it in place of a DAG turn.
3. **File measuring.** A new session's seed context is built with every item's statement and
   with every file either whole or as its reference, and kept; a later message only adds a file.
4. **The turn** runs as Synthetic defines it. Two things may hold it: a setup recommendation that
   is asked, and a security alert.
5. **Pruning.** When the turn ends, what it added to the session is judged and the part that adds
   nothing is cut out of it, the full log staying readable through the log tool.

Which steps a turn passes depends on where it came from:

| turn | match | file measuring | setup recommendation | security scan | pruning |
|---|---|---|---|---|---|
| a user's message | yes | yes | yes | yes | yes |
| the editor's send (the statement is the message) | no | yes | yes | yes | yes |
| a retry | no — as the retried turn | kept | kept | yes | yes |
| a message queued into a running turn | no | promotes | no | yes | yes |
| a delegated turn (agent call by item) | no | yes, against its statement | yes — on the setup it was started with | yes | yes |
| an off-context agent | — | none: no seed context | no | yes | no |
| a verdict agent | — | — | — | — | — |

Text the harness composes itself — a subagent's report header, `statement changed`, an extraction
mark — is never a message to match or estimate against.

## Stored state

**The state of a conversation is kept with its chat log** (`assassin_chats.json`), per chat, and
ends with the conversation's reset: the session's stored system prompt, its mark of unscanned
external text, the prune verdicts and the prune switches set by hand, the chat's recommendation
behaviour and the recommendations it denied.

**What the user accepted is kept for the user**, in `~/.ai-assassin/accepted_findings.json`: the
exact wording of every accepted finding of the security scan, with its category and the day it
was accepted. It belongs to no project and is the one file the Orchestrator writes outside the
chat log.

**Everything else is the server's memory** and is rebuilt by every run: the embedding vectors, the
scan verdicts and the miss records.
