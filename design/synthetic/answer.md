# Answer

A turn runs in **rounds**: the harness sends a prompt, the model hands back one **answer**. The
answer, the reply and the message are the harness's own protocol entities — no AI server defines
them, a connection only carries them.

- **Answer.** One object per round, `{"kind": "text"|"calls", "text", "calls": [...]}`
  (`synthetic.answer_schema`, built from the tool definitions of the prompt library), `text` and
  `calls` not exclusive.
- **Reply.** The `text` of a `kind: text` answer. It ends the turn and there is one per turn: what
  the chat shows last, what a delegating turn receives as its subagent's report, what the history
  of a new session keeps.
- **Calls.** A `kind: calls` answer is executed by the harness, the results going back into the same
  session as the next round's prompt; the results of changing calls go back like those of reads, and the exchange goes on until a text
  answer ends the turn.
- **Message.** A step of the turn holding what the model said on the way — the text beside the
  calls of an answer, split off rather than refused. It is shown in the log in its place and never
  reaches the caller of a subagent. A text is one message however many ways a connection reported
  it.

A malformed answer — invalid JSON, a call block cut off before its closing fence, an unknown tool,
a missing field, calls written as native tool-use markup with no call block, a text answer carrying
no text — is refused to the
model itself as its next prompt, naming what is wrong, within the rounds of the turn; nothing of it
is applied.

## Carriers

Every connection carries the same answer its own way:

| connection | the answer arrives as | its messages are |
|---|---|---|
| Claude Code | its kind and its calls as the input of the CLI's answer tool, `StructuredOutput`, which the CLI makes of `--json-schema` and requires once per round, and its text as what the model wrote ahead of that call — the schema handed to the CLI has no field for text | the text the model wrote ahead of a calls answer or of a tool call of the CLI's own |
| API connection | the completion's content: the JSON object `response_format` shapes, else a plain content whose calls sit in a fenced ```` ```syngate ```` block, the prose around it — leaked tool-use markup taken out — being the text beside them (`synthetic.split_reply`) | the text beside a calls answer |

The answer tool is the carrier, not a tool of the library: no item defines it as one and its call
is no step of the turn.

**One place for the text.** A completion is its answer, so an API connection cannot say the reply
twice. The CLI's model writes text blocks outside the answer tool whatever the schema says, so a
schema with a `text` field has it write the reply twice — as prose, then again in the tool — and
pay for both. The schema the Claude Code connector hands the CLI therefore carries `kind` and
`calls` alone and admits no other field, for a turn of an item and of an off-context agent alike: the
model writes its text once, as text, and closes the round with the tool. Nothing is generated twice
and nothing is dropped.

The connector holds a text block back until what follows tells which it is: a message once a tool
call of the CLI's own or a calls answer follows — it was said on the way — and the reply on a text
answer or at the closing `result`. The answer it returns to the harness is the object every
connection returns, the text put back into it, so nothing past the connector tells the carriers
apart. The reasoning written behind a held text waits with it and is a step either way, in its
place. A text answer with nothing written ahead of it carries no text and is refused like any
malformed answer. The structured answer skill (`call_tool_structured.md`, native delivery only) tells the
model to write its reply as text and to close the round with the tool, which takes no text.

**What each connection is told.** The tool call skill states the round every connection runs and
names no carrier. The answer object and the fenced block of a plain answer are told to connections
of text delivery alone (`call_tool_text.md`), the answer tool to those of native delivery alone, so
a model is never offered a way to answer its connection does not carry; what only the CLI does —
awaiting a workflow, killing a background shell at the turn's end — is told with the answer tool.
