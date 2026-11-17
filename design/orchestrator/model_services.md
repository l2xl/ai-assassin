# Model services

The Orchestrator owns no model. Every role it needs one for is given by the settings a **model
locator** — the connection, model and, for an agent, effort of a model of any connection of the
`connections` section, local or external — or a list of model locators, best first:

```json
{
  "orchestrator": {
    "embed":  {"connection": "cuda-4gb-embed",  "model": "bge-m3"},
    "rerank": {"connection": "cuda-4gb-rerank", "model": "bge-reranker-v2-m3"},
    "agents": {"default": [{"connection": "claude_code", "model": "haiku"},
                           {"connection": "mixroute",    "model": "claude-haiku-5-5"}],
               "scan":    [{"connection": "claude_code", "model": "haiku"},
                           {"connection": "mixroute",    "model": "claude-haiku-5-5"}]},
    "budget": 40000,
    "recommendations": "auto_lower"
  }
}
```

- **embed** — text to vector, the connection's `POST /embeddings`. A multilingual model, since the
  items are English and the messages need not be. Item vectors are kept in the server's memory alone, by the
  hash of the embedded text: they are computed when the server starts and again for a statement
  that changed, and never written to disk.
- **rerank** — a cross-encoder scoring (message, statement) pairs, the connection's `POST /rerank`.
  It is not part of the OpenAI API: llama.cpp and several providers serve it, and a connection says
  what it serves besides chat with `serves` (`embedding`, `reranking`), which also keeps it out of
  the chats' model menu.
- **agents** — the model locators of the off-context agents: `default` for every agent,
  an entry under an agent's name for that one.

**Fallbacks.** A role given a list is served by the first model locator of the list that answers.
The health check probes the list in order and stops at the first locator that passes; a call
failing on the locator in use marks it failed and moves the role on to the next one whose probe
passes — in the middle of a turn too, the call made again there. Every check starts again at the
head of the list, so a role comes back to its preferred locator once it answers. A single locator
is a list of one.

**Loaded model.** A locator whose model is `@loaded` — `{"connection": "gpu", "model": "@loaded"}` — names
no model of its own but whichever model its connection reports loaded: a llama.cpp router's
listing tells each model's load state, and the first `loaded` one in it serves the role. It is
resolved at every probe and every call, so a role follows the model the user switched the server
to and never asks the router to swap a model in for an orchestrator call; while nothing is loaded —
or the connection tells no load states — it fails like a locator that does not answer, and the role
moves on to its next locator. It suits the agents a model of any size serves; `embed` keeps a fixed
model, since its vectors and its threshold belong to one model. Embedding vectors are kept per connection and model, so a move of `embed` computes the
vectors anew in the other model's space and never compares vectors of two models.

**All of it is mandatory.** A chat dispatches nothing until every role names at least one model
locator — a connection that exists and a model it offers, or loads for `@loaded` — and one of them answers. The health of a role is checked when the server starts
and again whenever a call to it fails — not before every turn — and kept in between. While a role
fails — no locator of its list answering — the chat shows a **blocking alert** in place of the reply
line's hint: the role, every model locator it was tried on and what failed on each
(`rerank → cuda-4gb-rerank: connection refused, → gpu: no model 'bge-reranker-v2-m3'`), with a retry. Nothing degrades
silently to an unmeasured context or an unscanned change; a role failing in the middle of a turn
holds the turn on the same alert.

A message sent while the alert stands is not lost and not dispatched: it waits as the chat's
queued message, shown as queued, and is sent by itself once every role answers — on the alert's
retry or on the next health check that passes. The chat is **blocked** for as long as the alert
stands, with or without a turn.
