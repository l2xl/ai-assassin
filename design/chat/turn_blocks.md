# Turn steps in the log

- **Steps in order, no main message**. A turn is shown as it happened: every
  step is a block of the log of its own, in the order of the steps, and no reply is chosen to stand
  above the rest. The messages the AI said on the way — the text beside a batch of calls, an
  intermediate answer of a connector — are AI messages (`.chat-msg.ai.interim`), right as the reply
  and carrying its extraction marks but no fold, since they are not the reply's text. Every other
  step is a line of the harness (`.chat-step`), right with the AI's messages in the dim style of a
  secondary line, wrapping to a few lines and never merged with the next one: a tool call with its
  input, `reasoning` with its first line, every call of a `calls` batch on its own line — paired by
  the server with the call it answers (`inputs`) — every file of a `diff` on its own line
  (`added` / `changed` / `deleted`), a `workflow`, an `agent` step. Each line unfolds to the whole
  of it: a call to its input and its result (`read` for a reading call), a file to its hunks,
  reasoning to its text, an agent step to its prompt, report and nested transcript rendered by these
  same rules. The reply is the last block, a closing message the reply repeats is not shown twice. It is the AI's
  own text alone: the harness adds no line of the calls applied, which are blocks already, and a turn that ended on its calls shows no reply, only its blocks.
- **The activity line.** The reply closes with a dim line on its bottom rule — `7 tool calls ·
  2 subagents · 3 files changed · 48 s · $0.12` — the wall time and, when the connector reports
  them, the cost and token counts closing it, which a turn without steps still shows; it is a
  tally, never a fold.
