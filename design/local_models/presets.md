# Model presets

A **model preset** is a folder holding one `compose.yaml`: an independent docker compose project
of model servers — [llama.cpp](https://github.com/ggml-org/llama.cpp) or another engine — chosen for one kind of card. A
preset knows nothing of the others — its own project name (`assassin-<preset>`), containers,
network and volume of downloaded models — and runs without the command as well: `docker compose up
-d --wait` in its folder is the same thing.

Presets are found in two places, a project's own standing over a shipped one of its name:

- shipped with the package, `src/ai_scratcher/model_presets/<preset>/`;
- the project's `model_presets/<preset>/`, for a card or a choice of models of its own.

| preset | for | serves |
|---|---|---|
| `cuda-4gb` | a 4 GB NVIDIA card | the orchestrator's embedding and rerank models |
| `mi50-llamacpp` | the two 32 GB AMD Instinct MI50 cards of the user's server, llama.cpp | generic — no model defined |
| `mi50-strata` | the same cards, the Strata engine | generic — no model defined |

## What a preset's compose file holds

Besides what compose itself needs, the command reads three things of every service:

- **labels** — `ai-assassin.serve` (`embedding`, `reranking` or `chat`: what the server is switched
  to), `ai-assassin.model` (the model id it answers under) and `ai-assassin.memory-mb` (the card
  memory it is declared to hold);
- **its one port**, published on `127.0.0.1` alone — the servers carry no key;
- **its card**: a service reserving a device is one on the card.

The service's name is its **role**: its connection is `<preset>-<role>`, and a role named `embed`
or `rerank` is routed to the orchestrator's role of that name. The top-level `x-assassin` holds the
preset's `description` and, for a preset served elsewhere, the docker `host`.

A service states its own health check with a long `start_period`: a model's first start downloads
it, and the image's own check would call the container unhealthy long before the download ends.

## The command

`assassin-models [--root PATH] <command>`; the project root, whose `model_presets/` are offered
beside the shipped ones, is found as the `syngate` command finds it.

- **`list`** — the presets, each with its number of models, description and folder.
- **`up <preset>`** — serves the preset and is safe to repeat: compose leaves what is unchanged
  and replaces what changed. Before anything starts, the memory the models on the card declare
  together is checked against this machine's card (`nvidia-smi`); a preset that does not fit, or
  needs a card where there is none, is refused. The command waits until every service is healthy,
  within `--wait` seconds (900), then takes one real answer from every model — an embedding, a
  rerank, a completion — which also warms it. A service that did not come up fails the command
  with the tail of the project's log, a model that gave no answer by name.
- **`status [<preset>]`** — every model of the preset, or of all presets: the state and health of
  its container, `absent` without one, its port and what it serves. Docker not answering is an error,
  not an absence.
- **`probe <preset>`** — the real answers alone; healthy is not yet working.
- **`down <preset>`** — removes the project's containers. The volume stays, so the next `up`
  downloads nothing.
- **`routes <preset>`** — prints the settings that reach the preset, to be merged into
  `assassin_settings.json`: a connection per model and the orchestrator's routes. A connection of a
  model that serves no chat says what it `serves`, which is to keep it out of the chats' model menu — the key is written today and not read yet, so until then such
  a connection is still offered. A connection of a chat model lists the efforts `low`, `medium` and `high` with the reasoning budgets 1024, 2048 and 4096 tokens ([api_models.md](../connections/api_models.md)), the same whether llama.cpp or Strata serves it: both read `reasoning_effort` and `reasoning_budget_tokens` of every request and end a model's thinking at the budget.

## A preset on another machine

A preset naming a `host` (`x-assassin: {host: ssh://user@machine}`) is served there: every docker
call of the command goes to that host. The memory check is skipped, the card not being this
machine's, and the servers still listen on that machine's loopback — the ports are brought here by
an SSH tunnel, which is where the connections' `127.0.0.1` addresses point.
