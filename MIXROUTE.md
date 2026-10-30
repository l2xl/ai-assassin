# MixRoute connector

The MixRoute connector (`synthetic.mixroute_connector`, `mixroute` in the page's connector menu) is
the AI connection of AI Assassin to [MixRoute](https://mixroute.ai/docs/en/introduction), an
OpenAI-compatible API gateway giving one key to the models of many providers — Anthropic, OpenAI,
Google, DeepSeek, Zhipu, Kimi and more. Where the Claude Code connector drives a local agent with
its own file and shell tools, MixRoute answers over HTTPS with the model's text alone: a MixRoute
turn works the project only through the harness's tool calls — the tree calls, queries, test runs,
delegations, git and WebSurf — and never edits a file itself, so it lists no call modes of its
own; the harness's Tree edit and Interactive WebSurf switches are all the page shows for it.

## Settings

The connector is set up by the `mixroute` section of the server settings, `assassin_settings.json`
beside the tree ([ASSASSIN_UI.md](ASSASSIN_UI.md)), read anew at every use, so an edit takes
effect with the next turn and the next poll of the page, without a restart:

```json
{
  "mixroute": {
    "api_key": "sk-…",
    "base_url": "https://api.mixroute.ai/v1",
    "models": ["claude-sonnet-5-5", {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "efforts": []}],
    "default_model": "claude-sonnet-5-5",
    "default_effort": "medium",
    "structured": true,
    "timeout": 600,
    "smart_routing": {"api_key": "sk-route-…"}
  }
}
```

[assassin_settings.sample.json](assassin_settings.sample.json) is a ready setup: copy it to
`assassin_settings.json` beside the tree, then fill in `api_key` or leave it empty and export
`MIXROUTE_API_KEY`.

| key | meaning | without it |
|---|---|---|
| `api_key` | the MixRoute token, sent as `Authorization: Bearer …` | the environment variable `MIXROUTE_API_KEY`; with neither the connector is not offered |
| `base_url` | the API root the paths are appended to | `https://api.mixroute.ai/v1` |
| `models` | the models offered, each an id of the MixRoute model marketplace, or `{id, name, efforts}` | the built-in list (`synthetic.MIXROUTE_MODELS`) |
| `default_model` | the model a chat without a setup of its own starts with | the first model listed |
| `default_effort` | its effort, kept only when that model lists it | `medium` where the model lists it, else none |
| `structured` | whether the answer schema goes as `response_format` | `true` |
| `timeout` | seconds a request may wait for the next bytes of the answer | 600 |
| `max_tokens` | the output budget of a turn, reasoning included; an answer cut at it fails the turn instead of showing half its calls | 32000 |
| `smart_routing` | the routing key of smart routing, either a bare string or a section holding it as `api_key` | no key, so the connection's key goes with `auto` |

`smart_routing` is a section inside `mixroute`, read at every use like the rest. Smart routing is set
up per key in the MixRoute console: a route, its key, and a model for each of its three tiers, Simple,
Complex and Ultra. The page always lists `auto` first, ahead of the models of the settings; it stays
the default only when `default_model` names it. A turn of `auto` goes with the routing key
(`smart_routing.api_key`, else the connection's `api_key`, else `MIXROUTE_API_KEY`) and sends
`model: "auto"` with no `reasoning_effort`; MixRoute picks the tier by each request's complexity.

The key is better kept in the environment than in the file: `assassin_settings.json` is a plain file
beside the tree. A setup holding the key must keep the file out of git. A model the marketplace names
needs no change of the connector: listing its id in `models` offers it. The free model `glm-4-flash`
is offered by default, listed without efforts. A model listed as a bare id offers the efforts `low`, `medium` and `high`; one
taking no `reasoning_effort` is listed with `"efforts": []`, and its turns go without one.

Without an API key the connector stays out of the page's connector menu, and a chat whose setup
names it falls back to the first connector offered. A dispatch reached without a key all the same
fails with the error naming both places a key is read from.

## Turn

A turn is one streamed `POST <base_url>/chat/completions` request per round of the exchange:

- **Messages.** The seed context is the `system` message, at the head of every request, so the
  current statements are always the ones sent. The session's earlier messages follow, then the
  user's text as the last `user` message. With images (a WebSurf screenshot) that message's content
  is the text part followed by one `image_url` part each, its URL a `data:` URL of the base64 data.
- **Model and effort.** `model` is the chosen id unchanged. The chosen effort goes as
  `reasoning_effort` only when the model lists it, so a model without efforts is never sent one.
- **Library.** The connection declares `text` library delivery: the default prompt with the skills
  on request and every tool definition heads the seed context, and the `skill` call brings a skill's
  text back as the next prompt.
- **Answer.** With `structured` on, the answer schema of the library (`synthetic.answer_schema`)
  goes as `response_format` `{"type": "json_schema", "json_schema": {"name": "answer", "schema": …}}`,
  its description dropped since the seed context already carries the tool texts. An answer whose
  content is a JSON object — bare or in one fenced block — is the structured answer. `text` and
  `calls` are not exclusive in that schema, so a calls answer a model also gave a text is not
  refused as mixed: the text becomes a `message` step of the turn and the calls are the answer; a
  text answer carrying calls stays refused. Any other content is the reply text, so a model ignoring the schema still answers through the fenced
  `syngate` block the tool call skill describes. MixRoute does not enforce the schema on every
  model — Claude models answer in prose and fenced blocks whatever `response_format` says — and such
  a model may write a remark, or leak its native tool-use markup (`<invoke …>`), beside its one
  call block: the block alone is the answer and the remark, the markup taken out, a `message` step;
  two blocks stay refused. With `structured` off, no schema is sent.
- **Streaming.** `stream` is on, with `stream_options.include_usage`. The model's exposed reasoning
  (`reasoning_content`, or `reasoning`, in the deltas) is a `reasoning` step, announced as it grows.
  The closing usage chunk's `prompt_tokens` and `completion_tokens` make the turn's closing `usage`
  step, with its wall time. MixRoute reports no cost in the answer, so `cost_usd` stays empty.
- **Errors.** An HTTP error status fails the dispatch as a connection error naming the status and
  the API's own message (`error.message` of the body). So does an `error` object in the stream, an
  answer cut off without content, or a network failure. The table of statuses is MixRoute's
  [error codes](https://mixroute.ai/docs/faq/error-code.md).

## Session

The API is stateless, so the connector keeps the conversation itself, the way the `claude` CLI keeps
its sessions. A turn without a session opens one under a fresh id. The session's messages — each
user message and the answer to it, never the system prompt — are a JSON file
`<sessions dir>/<id>.json`, the sessions dir being `$XDG_STATE_HOME/ai-assassin/mixroute`
(`~/.local/state/…` without the variable), outside the project like the CLI's transcripts. A turn
resuming a session reads the file and sends its messages again. A session written only once the
answer is in leaves the file untouched by a failed or stopped request, so the retry of the same
message starts from the same history. A session id the folder does not hold — the folder cleared,
or the chat carried to another machine — fails the turn, asking for a new session; the page's
`↺ New session` then carries the kept messages as the transcript.

## Stop

The request is read by a worker thread, and the dispatch waits for its lines while it watches the
turn's stop. A stop (`interrupt`, or the turn's `stopped`) ends the dispatch at once as a connection
error. The worker closes the response at the next bytes it receives, which ends the stream on
MixRoute's side. Nothing of the
stopped request reaches the session. A stop before the request was sent sends none.
