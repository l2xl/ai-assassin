# Turn pruning

Much of what a turn adds to a session adds nothing to its meaning: a tree query the seed context
already answers, passing test output, a closing text restating the calls applied.

- **The tail at once, the rest when it pays.** Provider caches match the prefix of a request.
  Cutting from the turn that just ended changes only the tail and is done at once; cutting from
  an older turn resends everything after it uncached. A verdict on a turn ahead of the tail — a
  late one, a superseded reading, a switch — therefore waits for the **pruning worth**: it is
  brought into the running session with the next message once the provider's cache of the session
  expired (its last request five minutes ago or more) or the cut takes out at least as many tokens
  as the request then resends uncached.
- **By rule, without a model:** the result of a tree read, the re-read of a file the system prompt
  holds whole, the output of a passing run, and a batch of applied calls down to one line each.
  A **superseded reading** goes the same way in whatever turn it stands: a step that only read —
  a query, a context, a file read — is pruned once every item and file it read was read again
  later, by a call or in a context update, or changed by a call of the session since. The latest
  reading alone stays; a step that also did something else is no reading to supersede.
- **By the prune agent:** an AI text, kept when it states something the session does not hold,
  cut when it restates or is superseded by a later text of the turn, its closing reply above all;
  and an **unused reading** — a file read, a tree read or a search result the turn changed nothing
  by and its conclusions do not rest on — cut to its stub. The agent is given the turn's texts and
  the one-line stubs of the turn's steps, every reading named by what it read and numbered apart,
  not the session and no result. The user's messages are never candidates.
- **Stubs.** A cut step leaves one line naming its turn and step and what it was (`[turn 7 step 3:
  test run, 12 passed — read with log]`), carried in the harness's next message, never written
  into an AI message.
- **Pruned is a state of its own**, not the user's fold. A pruned message stays in the log in full
  under its mark. The **prune switch** is that mark, on every step line and AI message of the log,
  the user's messages aside: dim `prune` on what the session holds, `pruned` on what it does not;
  a click returns a pruned one to the session or cuts a kept one. It takes effect with the chat's
  next message, brought into the running session, which is not ended for it — and, being the
  user's act, it asks no worth. The user's fold stays what it was: text the user took out of the
  exchange.
- **Late verdicts.** When the next message arrives before the prune agent answered, its turn is
  no longer the tail: the agent's verdicts count as ones on a turn ahead of the tail and wait for
  the pruning worth.
- **Who brings a verdict in.** A session the harness writes — an API connection's message list —
  is cut in place. A session its connection owns takes the verdicts through that connection's
  replay, under the same worth, and is never restarted for them; a connection offering neither
  holds them until the conversation's next session.
- **Session continuity.** No token bound ends a turn, restarts the session or stands in the
  settings. The size of the session — the input tokens of its last request — is kept and feeds the
  worth; what the session holds shrinks only by the prune verdicts brought into it.
- **New session head.** A conversation that starts a session anew — after a reset, a fold changed
  by hand, a new connection or model — heads it with its turns as the pruning holds them: the
  user's messages, the AI texts and every step result no verdict cut, the stubs standing where the
  cut ones stood, each line told as the user's, the assistant's or the harness's. It is never the
  message texts alone, so a file the turn read and still rests on reaches the new session.
- **The log tool** reads back what was pruned — not what the user folded
  out, nor what a security finding dropped.
