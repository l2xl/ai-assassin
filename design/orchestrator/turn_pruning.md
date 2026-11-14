# Turn pruning

Much of what a turn adds to a session adds nothing to its meaning: a tree query the seed context
already answers, passing test output, a closing text restating the calls applied.

- **At the turn's end, once.** Provider caches match the prefix of a request. Cutting from the
  turn that just ended changes only the tail; cutting from an older message would invalidate
  everything after it. So a message's fate is decided when its turn ends and not revisited within
  the session.
- **By rule, without a model:** the result of a tree read, the re-read of a file the system prompt
  holds whole, the output of a passing run, and a batch of applied calls down to one line each. A
  file read for the first time stays — it is the working set the model chose to fetch.
- **By the prune agent:** an AI text, kept when it states something the session does not hold,
  cut when it restates. The agent is given the turn's texts and the one-line stubs of the turn's
  steps, not the session. The user's messages are never candidates.
- **Stubs.** A cut step leaves one line naming its turn and step and what it was (`[turn 7 step 3:
  test run, 12 passed — read with log]`), carried in the harness's next message, never written
  into an AI message.
- **Pruned is a state of its own**, not the user's fold. A pruned message stays in the log in full
  under a dim `pruned` mark; its **prune switch** returns it to the session or — on a message the
  harness kept — cuts it. A switch changed by hand is a verdict for the conversation's next
  session and does not end the running one. The user's fold stays what it was: text the user took
  out of the exchange.
- **Late verdicts.** When the next message arrives before the prune agent answered, the rule
  verdicts apply alone and the agent's wait for the next session.
- **Session renewal.** A session the harness cannot rewrite — the Claude Code CLI's transcript — would
  otherwise hold every waiting verdict until a reset, a fold changed by hand or a new setup, and grow
  until its connection compacts it by a summary of its own: the lossy summary this design refuses.
  So once the last request of the running session took the renewal bound of input tokens or more
  (`renew_tokens` of the `orchestrator` settings, 100000 by default, 0 never) — the size the turn's
  last `usage` step counts, cache reads included — the conversation's next message, a retry aside,
  starts its next session: the verdicts that waited and the switches set by hand apply, the kept
  messages head it with the stubs, the seed context is measured anew, and the turn says so in a
  context step. The one uncached prefix it costs is paid where every request of the old session
  was already paying for its whole length. A session the harness rewrites is renewed by the same
  bound, its late verdicts and switches applying then.
- **The log tool** reads back what was pruned — not what the user folded
  out, nor what a security finding dropped.
