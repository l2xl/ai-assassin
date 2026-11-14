# Agent match

A message asking for work that needs no item context is handed to the off-context agent that does it.

- **Gate.** The embedded message is ranked against the agents — each by its best `example` — and
  the statements of the items together, and an element is *in* when its cosine reaches the match
  threshold (`orchestrator.match_threshold` of the server settings, 0.75 by default). No agent in:
  the message stays with the DAG and nothing is asked of a model — the usual message costs no call
  here. One agent in and nothing else: that agent runs, still with no call.
- **Confirmation.** Several elements in, an agent among them: the match agent answers
  `{"agent": "<name>" | null}` over the message, the conversation's last exchange and the agents
  in alone — the items are dropped. Only a confirmed agent runs: a message that merely mentions
  testing (`why does the queue test fail?`) stays with the DAG, and so does every doubt. The
  question is narrow, so it runs on a cheap model: the `orchestrator.agents.match` model locator of the
  server settings, else Claude Code's `haiku` at `low` effort.
- **In the conversation.** The matched message and the agent's report are messages of the chat's
  log and of its session, so a later `what did you commit?` finds them.
