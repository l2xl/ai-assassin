# API connection models

A model listed as a bare id offers the connection's `efforts`; one taking no `reasoning_effort` is
listed with `"efforts": []`, and its turns go without one. `model` is the chosen id unchanged.

**Reasoning budget.** A connection's `reasoning_budgets` maps efforts to token counts, `{"low": 1024, "medium": 2048, "high": 4096}`, and a turn at an effort the table names sends that count as `reasoning_budget_tokens` beside `reasoning_effort`; an effort the table leaves out goes alone, and a model listing no efforts sends neither. The effort is only an instruction the model may disregard — a Qwen model at its template's default thinks without end — and the budget is the hard limit: a llama.cpp server, which also reads the field as `thinking_budget_tokens`, takes it over its server-wide `--reasoning-budget`, and a Strata server over the `reasoning_budget_tokens` of its model's config file; each ends the thinking at that many tokens and lets the model answer from there. llama.cpp applies it only for a chat template that marks the end of thinking, and a build older than the field ignores it. A server that does not know the field ignores it, so a gateway that rejects unknown fields is simply given no table. An entry that is not a positive whole number is left out of the table. No server reports the efforts or budgets of its models in its listing — a llama.cpp `/props` tells only the levels a chat template renders distinctly, per model and so, on a router, one request for each, and a Strata listing carries none — so the default table of a local engine's queried models is fixed here, and a server not recognised as one, a gateway that may reject the field, is given none until its connection declares a table.

**Queried models.** With `"models": "query"` the models are the listing of the server's
`GET <base_url>/models`, asked with the connection's key, kept a few seconds and asked again after;
a listing that fails offers no model, so the connection stays out of the page until the server
answers. A queried model of a server that reports load states — a llama.cpp router — or names `llamacpp` as the owner of its models is offered under its id with the efforts `low`, `medium` and `high`, their budgets 1024, 2048 and 4096 tokens; a queried model of any other server is offered only the efforts the connection's `reasoning_budgets` give a budget, in the table's order, and none without one. A table the connection declares replaces the default one. A llama.cpp server in router mode
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
