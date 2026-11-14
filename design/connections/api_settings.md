# API connection settings

The connections are the `connections` section of the server settings, `assassin_settings.json`
beside the tree, read anew at every use, so an edit takes effect
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
                 {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "efforts": [], "family": "deepseek", "tier": 2,
                  "strengths": "long prose and cheap drafts"}],
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
| `models` | the models offered, each an id, or `{id, name, efforts, family, tier, strengths, api_key}` — `family` and `tier` as *Model family* below states, `strengths` one line telling what the model is the right choice for, all reported with the model; or `"query"` for the server's own listing | nothing offered |
| `efforts` | the efforts of a model listed as a bare id | `low`, `medium`, `high` |
| `reasoning_budgets` | the token budget of each effort, `{"low": 1024, "medium": 2048, "high": 4096}`, sent as `reasoning_budget_tokens` with a turn at that effort, and the efforts a queried model offers | for a queried llama.cpp model 1024, 2048 and 4096 for `low`, `medium` and `high`, for any other model no budget |
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

**Model family.** A model entry may declare the `family` it belongs to — a non-empty string naming a line of
models, `claude` or `deepseek` — and, beside it, its `tier`, a number placing it within that line, a larger
tier the stronger model. The connection's settings report both with that model; a model declaring no family,
listed as a bare id or taken from the server's own listing is reported with neither, and a `tier` that is no
number, or stands without a `family`, is left out.

**Offer.** The page offers every configured connection by its id after the built-in connectors, in
the order of the section, while it has a model to offer and its declared key is set. A chat whose
setup names a connection no longer offered falls back to the first connector offered.

**Trusted certificates.** A server with a certificate of its own — self-signed, or signed by a
private CA — is reached by naming the certificate (or its CA's) in `ca`: those files are trusted
for that connection's requests on top of the system store, so the other connections are not
affected. The certificate must name the host the base URL uses, an IP address as an `IP:` subject
alternative name.
