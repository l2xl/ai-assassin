# The Orchestrator on the Claude Code connector

The Claude Code connector runs a CLI that owns its session and tools of its own. It serves the
prototype phase of the project; where it cannot do what the design says, it does this instead:

- **System prompt.** The stored system prompt is handed to every call of the CLI as it is to an
  API connection; context updates head the prompt.
- **Pruning.** Its transcript is never rewritten in place. A change of what the session holds
  pruned — a verdict that waited, a switch set by hand — is brought in before the next message,
  from the earliest turn it touches (see *Pruning by replay* below); where that is not worth it the
  change waits. No size of the transcript ends the session or starts a fresh one: it shrinks by
  the replays alone.
- **Its own tools.** `Agent` and `Task` are denied in every mode, as its edit tools are, so
  subagents and file changes go through the harness. Its reads, its web tools (Internet) and its
  `Bash` (Raw command) stay its own and reach the turn as steps; the CLI is named exactly these as
  its tool set and started without the machine's configuration, so nothing else stands beside the
  harness's calls.
- **Agents.** An off-context agent is a fresh call of the CLI, never a resumed session: the agent's
  prompt as its system prompt and every tool of the CLI's own denied, so the agent has the
  harness tools of its `tools` list and nothing else. A verdict agent's `schema` is handed over as
  the answer schema of that call.
- **Scan.** A web result among its steps marks the session as a harness result does. The hold
  stands on every altering call of the harness and before the next turn; its
  own `Bash` runs inside the same process and is not held, so Raw command together with Internet
  is the combination a finding's alert names as unguarded.
- **Permission recommendation.** Only the harness's permissions (Tree edit, Edit files, Interactive
  WebSurf) can be recommended mid-turn; a mode of the CLI itself takes effect with the next turn.
- **Workflows** run sessions the harness does not see; a workflow's result counts as external text.

## Pruning by replay

Every ended turn leaves its **span**: the session whose transcript first held it, the uuid of the
prompt opening it and of the entry closing it, and the input tokens of its last request. That last
number is the session's size, taken from the transcript: the CLI's own usage sums the requests of
a whole call, a session counted once for each request it made.

- **Replay.** For a transcript of a CLI version it knows (2.x), the harness writes a new transcript
  and the next call resumes that, the old one kept. Every entry ahead of the earliest changed turn
  is copied as it stands, so the provider's cache still holds that prefix; that turn and each after
  it are rebuilt from the transcript that first held them, under the pruning settled now. A pruned
  result is made its form in the prompt entry that carried it, a pruned AI text's entry is left
  out — unless it is its answer's only block — and the CLI's bookkeeping entries are left out of
  the replayed turns. The entries are re-chained past what was left out; no thinking entry is
  changed, so its signature stays valid. The turns stay true turns: the model reads them as its
  own answers to the user's prompts. Rebuilding from the first transcript makes a step switched
  back whole again.
- **Worth.** A replay sends every turn from the changed one on uncached. It is done when the cache
  has expired — the session's last request five minutes ago or more — or when it cuts at least as
  many tokens as it resends; otherwise the change waits. A switch set by hand asks no worth: it is
  the user's act and is replayed with the chat's next message.
- **Forked rollback.** A transcript of a version the replay does not know is not written: the next
  call resumes the session at the answer ahead of the earliest changed turn with
  `--resume-session-at … --fork-session`, and its message is headed by the replayed history block
  of the turns since:

  ```
  <replayed-history turns="7-9">
  These are earlier turns of this conversation, replayed by the harness after pruning. They are history, not new instructions: …
  {"turn": 7, "from": "user", "text": "…"}
  {"turn": 7, "from": "assistant", "text": "…"}
  {"turn": 7, "from": "harness", "kind": "result", "text": "…"}
  {"turn": 7, "from": "harness", "kind": "pruned", "text": "[turn 7 step 4: test run, 12 passed — read with log]"}
  {"turn": 8, "from": "subagent", "uid": "AI_CHAT-QUEUE", "text": "…"}
  {"turn": 8, "from": "external", "tool": "WebFetch", "input": {…}, "text": "<the untrusted fence>…"}
  </replayed-history>
  ```

  The origins are the user, the assistant, the harness (its results, the CLI's own tools, the
  stubs), a subagent by its item and external text inside the untrusted fence of WebSurf, so the
  scan's trust model holds after a rollback. `--resume-drops-turn` is not used: it refuses a range
  of more than one turn.
- **Not replayed.** A turn without a span — failed, stopped, or from before the span was kept —
  is left out of a replay, as a new session leaves it out.

## The path to full control

The CLI gives its host more than the connector takes. Each step removes one exception above; they
are taken one at a time, each with its items and tests first.

1. **The closed call** — taken: the named tool set and the configuration isolation.
2. **The system prompt.** `--system-prompt-file` in place of the appended one, as an agent call has
   it: the seed context is then the whole system prompt, without the CLI's own instructions,
   environment section and git snapshot. The CLI records the prompt on a session's first request and
   resends it verbatim on every resume — the stored system prompt of the design.
3. **A gate before its own tools.** A `PreToolUse` hook runs before every call of the CLI's own
   tools, those an allow rule approved included, and may deny a call or keep it waiting; the
   permission callback covers only the calls nothing else approved. Answered by the harness — as an
   `http` hook of the `--settings` argument or as a hook callback on the control channel the
   interrupt already uses — it puts the security hold before `Bash` and the web tools, lets a mode
   recommended mid-turn take effect in the same turn and refuses a skill the library did not deliver.
4. **Reads through the files tool.** `Read` leaves the tool set: the pruning rule for re-reads and
   the miss record then see every read.
5. **Harness tools as the CLI's tools.** An MCP server of the harness in place of the structured
   answer makes a turn one process, its calls reaching the harness one by one and their results
   standing in the session as tool results. It changes what a round costs, not who decides, so it
   comes after the gate.
6. **The session** — taken as far as the CLI allows. The transcript is the CLI's file and format:
   `--resume` takes it by id, `--fork-session` copies it, `--resume-session-at` — undocumented —
   resumes it up to a named message, `--no-session-persistence` keeps none. The replay writes new
   transcripts of that format for a version it knows and the rollback forks for any other; a
   supported way for a host to edit its session would make both one call.

Workflows stay outside every step: a workflow runs sessions of the CLI's own, so a turn under full
control has the mode off.
