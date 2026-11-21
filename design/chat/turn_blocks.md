# Turn steps in the log

- **Steps in order, no main message**. A turn is shown as it happened: every
  step is a block of the log of its own, in the order of the steps, and no reply is chosen to stand
  above the rest. The messages the AI said on the way — the text beside a batch of calls, an
  intermediate answer of a connector — are AI messages (`.chat-msg.ai.interim`), right as the reply
  and carrying its extraction marks but no fold, since they are not the reply's text. Every other
  step is a line of the harness (`.chat-step`), right with the AI's messages in the dim style of a
  secondary line, wrapping to a few lines and never merged with the next one: a tool call with its
  input, `reasoning` with its first line, every file of a `diff` on its own line
  (`added` / `changed` / `deleted`), a `workflow`, an `agent` step. Each line unfolds to the whole
  of it: a tool call to its input and its result, a file to its hunks, reasoning to its text, an
  agent step to its prompt, report and nested transcript rendered by these same rules.
- **Call lines.** A `calls` batch is one answer of the AI carrying a list of calls, applied in
  order, the first refusal ending it; the results of all of them go back as one prompt. The server
  announces the batch as the answer arrives — `pending`, the calls not answered yet; a connection
  that learns the calls before it can return the answer, as the Claude Code connector does when its
  answer tool is called, tells them at once and the batch is announced then — and again with
  every result, each paired with the call it answers (`inputs`); once the batch is over the calls it
  never ran are its `skipped`. Every call is two lines: the request (`.call-request`) — the tool and
  the call's main fields, unfolding to the call — and under it the response (`.call-response`),
  its fold handle under the first letter of the request's tool name: the text the AI is sent for the call — less its
  leading `- ` and a first line that only names the call again, a heading ending in `:` over more
  lines (`grep`, `read`, `log`, `context`, `test`…); a one-line result is kept whole — verbatim
  — its line breaks kept, no markdown rendered — in one body styled as an AI message's
  (`.call-text`), under no label or summary of the harness. It starts level with its
  fold handle, on the handle's own line, and spans the same width whatever its text: from the
  handle to a fixed column kept at the right for the prune mark (`.prune-mark`), which stands in
  it level with the first line. Folded, the body is clamped to its first two lines; its handle, a triangle alone named by its `aria-label`, lifts the clamp in
  place, the text never shown a second time. Until the call is answered its response tells `running` for the
  first call waiting, `waiting` for the ones after it, and `not run` for a call the batch ended
  before. A turn held on a recommendation shows it right under the request line of the call it
  holds, the rest of the turn shown around it. The reply is the last block, a closing message the reply repeats is not shown twice. It is the AI's
  own text alone: the harness adds no line of the calls applied, which are blocks already.
- **The activity line.** The reply closes with a dim line on its bottom rule — `7 tool calls ·
  2 subagents · 3 files changed · 48 s · $0.12` — the wall time and, when the connector reports
  them, the cost and token counts closing it, which a turn without steps still shows; it is a
  tally, never a fold.
