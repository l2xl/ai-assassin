# API connection turn

A turn is one streamed `POST <base_url>/chat/completions` request per round of the exchange:

- **Messages.** The seed context is the `system` message, at the head of every request, so the
  current statements are always the ones sent. The session's earlier messages follow, then the
  user's text as the last `user` message. With images (a WebSurf screenshot) that message's content
  is the text part followed by one `image_url` part each, its URL a `data:` URL of the base64 data.
- **Effort.** The chosen effort goes as `reasoning_effort` only when the model lists it, so a model
  without efforts is never sent one.
- **Library.** The connection declares `text` library delivery: the default prompt with the skills
  on request and every tool definition heads the seed context, and the `skill` call brings a skill's
  text back as the next prompt.
- **Answer.** With `structured` on, the answer schema of the library (`synthetic.answer_schema`)
  goes as `response_format` `{"type": "json_schema", "json_schema": {"name": "answer", "schema": …}}`,
  its description dropped since the seed context already carries the tool texts. llama.cpp turns the
  schema into a grammar the model's content keeps to. An answer whose content is a JSON object — bare
  or in one fenced block — is the structured answer. `text` and `calls` are not exclusive in that
  schema, so a calls answer a model also gave a text is not refused as mixed: the text becomes a
  `message` step of the turn and the calls are the answer; a text answer carrying calls stays
  refused. Any other content is the reply text, so a model ignoring the schema still answers through
  the fenced `syngate` block the tool call skill describes. A gateway does not enforce the schema on
  every model — Claude models behind MixRoute answer in prose and fenced blocks whatever
  `response_format` says — and such a model may write a remark, or leak its native tool-use markup
  (`<invoke …>`), beside its one call block: the block alone is the answer and the remark, the markup
  taken out, a `message` step; two blocks stay refused. Markup naming a tool (`<invoke name="shell">`) with no call block
  beside it is the model's calls written where the harness does not read them: the answer is refused back to the model, asking for
  the block, instead of ending the turn as a text reply with the calls unrun. With `structured` off, no schema is sent.
- **Format fallback.** Providers behind one gateway hold different subsets of `response_format`. A request
  the server refuses for it — a `400` or `422` whose message names `response_format` or `json_schema` —
  goes again with the schema in the strict form OpenAI requires, then without a schema; any other
  refusal fails the turn at once. The strict form lists every property of an object as required, an
  optional one taking `null` besides, gives every `const` and `enum` its `type`, and merges the call
  shapes into one call object — `tool` the enum of every tool, the fields of all of them — since a
  strict decoder writes the keys in its own order and cannot tell shapes apart by a `tool` it writes
  last; the fields a strict answer fills with `null` are dropped and each tool's required fields are
  checked when the answer is parsed. The connection keeps the form that served per model for as long
  as the server runs, so OpenAI models go strict and DeepSeek's without a schema from their second
  turn on, answering through the fenced `syngate` block.
- **Streaming.** `stream` is on, with `stream_options.include_usage`. The model's exposed reasoning
  (`reasoning_content`, or `reasoning`, in the deltas) is a `reasoning` step, announced as it grows.
  The closing usage chunk's `prompt_tokens` and `completion_tokens` make the turn's closing `usage`
  step, with its wall time. The API reports no cost in the answer, so `cost_usd` stays empty.
- **Errors.** An HTTP error status fails the dispatch as a connection error naming the connection's
  label, the status and the API's own message (`error.message` of the body). So does an `error`
  object in the stream, an answer cut off without content, or a network failure — a certificate the
  connection does not trust among them. MixRoute's statuses are its
  [error codes](https://mixroute.ai/docs/faq/error-code.md).
