# OpenAI-compatible API connections

An OpenAI-compatible API connection (`api_connection.api_connection`, module
`src/ai_scratcher/api_connection.py`) is an AI connection of AI Assassin to any server speaking the
OpenAI chat completions API: a gateway such as [MixRoute](https://mixroute.ai/docs/en/introduction),
giving one key to the models of many providers, or a self-hosted [llama.cpp](https://github.com/ggml-org/llama.cpp)
`llama-server`. The server settings configure as many connections as wanted, each by an id of its
own, and the page offers them side by side next to the Claude Code connector. Where the Claude Code
connector drives a local agent with its own file and shell tools, an API connection answers with the
model's text alone: its turn works the project only through the harness's tool calls — the tree
calls, queries, test runs, delegations, git and WebSurf — and never edits a file itself, so it lists
no call modes of its own; the harness's Tree edit, Edit files and Interactive WebSurf switches are all
the page shows for it.

The module depends on `synthetic` for the connection error, the prompt library and the answer
schema; `synthetic` does not import it, and the AI Assassin server builds the connections from the
settings next to the connectors `synthetic.CONNECTORS` names.

## Settings

The connections are the `connections` section of the server settings, `assassin_settings.json`
beside the tree ([ASSASSIN_UI.md](ASSASSIN_UI.md)), read anew at every use, so an edit takes effect
with the next turn and the next poll of the page, without a restart. The section maps each
connection's id — the name the page's chats record as their connector — to its setup:

```json
{
  "connections": {
    "mixroute": {
      "label": "MixRoute",
      "base_url": "https://api.mixroute.ai/v1",
      "api_key_env": "MIXROUTE_API_KEY",
      "models": [{"id": "auto", "efforts": [], "api_key": "sk-route-…"}, "claude-sonnet-5-5",
                 {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "efforts": []}],
      "default_model": "claude-sonnet-5-5",
      "default_effort": "medium"
    },
    "gpu": {
      "label": "GPU server",
      "base_url": "https://gpu.example:8443/v1",
      "api_key": "…",
      "ca": "certs/gpu.pem",
      "models": "query"
    }
  }
}
```

[assassin_settings.sample.json](assassin_settings.sample.json) is a ready setup: copy it to
`assassin_settings.json` beside the tree and fill in the keys, or leave them empty and export the
variables the entries name.

| key | meaning | without it |
|---|---|---|
| `label` | the name the page shows, and the one connection errors start with | the id |
| `base_url` | the API root the paths are appended to | none: the connection is not offered |
| `api_key` | the token sent as `Authorization: Bearer …` | the variable `api_key_env` names |
| `api_key_env` | the environment variable holding the token | no variable |
| `models` | the models offered, each an id, or `{id, name, efforts, api_key}`; or `"query"` for the server's own listing | nothing offered |
| `efforts` | the efforts of a model listed as a bare id | `low`, `medium`, `high` |
| `default_model` | the model a chat without a setup of its own starts with | the first model |
| `default_effort` | its effort, kept only when that model lists it | `medium` where the model lists it, else none |
| `structured` | whether the answer schema goes as `response_format` | `true` |
| `timeout` | seconds a request may wait for the next bytes of the answer, a model load included | 600 |
| `max_tokens` | the output budget of a turn, reasoning included; an answer cut at it fails the turn instead of showing half its calls | 32000 |
| `ca` | PEM file, or list of them, trusted besides the system's certificates; relative to the project root | the system's certificates only |
| `load_retries` | times a turn refused because its model did not load is sent again | 2 |

**API key.** A connection declaring a key — naming `api_key` or `api_key_env` — is offered only
while the key resolves, and a dispatch reached without it all the same fails with the error naming
both places a key is read from. A connection declaring neither sends no `Authorization` header: a
llama.cpp server on loopback, or reached through an SSH tunnel, needs none. A model entry's own
`api_key` goes with that model's turns in place of the connection's, an empty one falling back to
it; that is how MixRoute's smart routing is set up — the model `auto` listed with the routing key,
MixRoute picking the Simple, Complex or Ultra tier of the route by each request's complexity. No key
ever reaches the page: the settings the page reads list the models without them.

The keys are better kept in the environment than in the file: `assassin_settings.json` is a plain
file beside the tree, and a setup holding a key must keep the file out of git.

**Offer.** The page offers every configured connection by its id after the built-in connectors, in
the order of the section, while it has a model to offer and its declared key is set. A chat whose
setup names a connection no longer offered falls back to the first connector offered.

**Trusted certificates.** A server with a certificate of its own — self-signed, or signed by a
private CA — is reached by naming the certificate (or its CA's) in `ca`: those files are trusted
for that connection's requests on top of the system store, so the other connections are not
affected. The certificate must name the host the base URL uses, an IP address as an `IP:` subject
alternative name.

## Models

A model listed as a bare id offers the connection's `efforts`; one taking no `reasoning_effort` is
listed with `"efforts": []`, and its turns go without one. `model` is the chosen id unchanged.

**Queried models.** With `"models": "query"` the models are the listing of the server's
`GET <base_url>/models`, asked with the connection's key, kept a few seconds and asked again after;
a listing that fails offers no model, so the connection stays out of the page until the server
answers. A queried model is offered under its id without efforts. A llama.cpp server in router mode
(`llama-server --models-dir …`) reports each model's load state — `unloaded`, `loading`, `loaded`,
`sleeping` — and the page shows it beside the model's name.

**Router server.** A connection whose listing reports load states is a llama.cpp router; its model
endpoints are at the server root, the base URL without its trailing `/v1`:

- *Immediate load.* Choosing a model in a chat's menu asks the router to load it at once —
  `POST <root>/models/load {"model": id}` — when it is not loaded or loading already, so the load
  runs while the user writes. The router keeps `--models-max` models loaded, unloading the least
  recently used one for a new one.
- *A turn on a loading model.* The router holds a chat request for a model being loaded — or one not
  loaded at all, which it loads first — and answers once the load is done, a queued request for
  another model waiting its turn for the slot. The turn just waits; its `timeout` must cover a load,
  about 40 s for a 20 GB model read from the page cache and more from disk.
- *Prompt progress.* A llama.cpp server sends nothing while it reads a prompt — no headers even — and
  a turn anchored high in the tree carries a long one: the whole tree under the root with its key
  sources is some 200k tokens, which a 27B model on one MI50 reads at about 200 tokens a second,
  slowing as the context grows. A turn on a router asks for `return_progress`, so the server streams
  a `prompt_progress` chunk — tokens processed, total and cached, milliseconds spent — after every
  batch. The connection records them as one `prompt` step growing with the tokens read, which the
  page shows with its percentage, and the bytes keep the request alive: `timeout` counts real
  silence, never the reading of a prompt. A gateway is never sent the field.
- *A load that falls over.* A load stopped before it finished — the model unloaded meanwhile, or its
  process killed — fails the requests waiting on it with `500 … failed to load`, and a router started
  with `--no-models-autoload` refuses a model not loaded with `400 model is not loaded`. Such a
  refusal comes before any answer, so the turn asks for the load and sends the same request again, up
  to `load_retries` times; any other error fails the turn at once.

## Turn

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
  taken out, a `message` step; two blocks stay refused. With `structured` off, no schema is sent.
- **Streaming.** `stream` is on, with `stream_options.include_usage`. The model's exposed reasoning
  (`reasoning_content`, or `reasoning`, in the deltas) is a `reasoning` step, announced as it grows.
  The closing usage chunk's `prompt_tokens` and `completion_tokens` make the turn's closing `usage`
  step, with its wall time. The API reports no cost in the answer, so `cost_usd` stays empty.
- **Errors.** An HTTP error status fails the dispatch as a connection error naming the connection's
  label, the status and the API's own message (`error.message` of the body). So does an `error`
  object in the stream, an answer cut off without content, or a network failure — a certificate the
  connection does not trust among them. MixRoute's statuses are its
  [error codes](https://mixroute.ai/docs/faq/error-code.md).

## Session

The API is stateless, so the connection keeps the conversation itself, the way the `claude` CLI keeps
its sessions. A turn without a session opens one under a fresh id. The session's messages — each
user message and the answer to it, never the system prompt — are a JSON file
`<sessions dir>/<session>.json`, the sessions dir being `$XDG_STATE_HOME/ai-assassin/<connection id>`
(`~/.local/state/…` without the variable), outside the project like the CLI's transcripts; the
connection id `mixroute` keeps the sessions of the former MixRoute connector. A turn resuming a
session reads the file and sends its messages again. A session written only once the answer is in
leaves the file untouched by a failed or stopped request, so the retry of the same message starts
from the same history. A session id the folder does not hold — the folder cleared, or the chat
carried to another machine — fails the turn, asking for a new session; the page's `↺ New session`
then carries the kept messages as the transcript.

## Stop

The request is read by a worker thread, and the dispatch waits for its lines while it watches the
turn's stop. A stop (`interrupt`, or the turn's `stopped`) ends the dispatch at once as a connection
error, a wait for a loading model included, and shuts the request's socket down from the
dispatching thread: the worker's blocked read fails, and the server sees the client gone even when
it has not begun to answer — a llama.cpp server then cancels the task, freeing the GPU of a prompt
it was still reading. The connections a request opens are held for that, wrapping urllib's own, so
proxies from the environment still apply; one that connects after the stop closes before it sends.
Nothing of the stopped request reaches the session. A stop before the request was sent sends none.
