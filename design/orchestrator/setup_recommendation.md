# Setup recommendation

One algorithm produces a **recommendation** — a change of the chat's setup the turn at hand
needs — and one layer above it, the chat's **behaviour**, decides whether the recommendation is
applied at once or asked of the user. The two are independent: how a recommendation was made
never depends on the behaviour, and the behaviour never looks at how it was made.

## What is recommended

- **A model.** Whether the task of a message is better served by another model is judged by
  **the model the chat runs on** — it holds the seed context and the message, which is what the
  judgement needs — and it judges knowing the alternatives, not a scale: which model suits a task
  depends on what the task is and on which connections this server has.
- **A permission.** A call the harness would refuse only because a permission switch is off is
  held, not refused, and the harness itself recommends switching that permission on. The model
  takes no part: it sees its call applied or refused.

## The alternatives

What a model is good for is stated where the model is configured, in the settings of its
connection:

```json
"models": [{"id": "claude-sonnet-5-5", "family": "claude", "tier": 2,
            "strengths": "coding, structured output such as SVG"},
           {"id": "gpt-5", "family": "gpt", "tier": 3,
            "strengths": "prose a person reads: documents, letters"},
           {"id": "qwen3-coder", "family": "qwen", "tier": 1,
            "strengths": "local and free: short routine work, an off-context commit"}]
```

- **family** — the line of models a model belongs to; one connection may carry several, and
  several connections the same one.
- **tier** — its place within its family, a larger number the stronger and dearer model. Tiers
  of different families are not compared.
- **strengths** — a line, in words, on what the model is the right choice for.

The assessment skill, a default skill, has every turn weigh the task against the model it runs
on — first when the session opens, again whenever the task turns out lighter or heavier than it
looked — and, in doubt, read the alternatives and recommend one. It
describes the two dimensions of a choice:

- **along the family** — the same kind of model, weaker or stronger: `sonnet` to `opus` for a
  hard design, `sonnet` to `haiku` for a rename;
- **across families** — a model of another behaviour: a prose model for a document meant for
  people, a local one for an off-context routine job.

## When a model may be recommended

- **At any time.** The assessment skill is in place from a session's first turn and its
  judgement is never final: a review that came back, a failed attempt or a new message of the
  user changes what the task weighs, and the model may answer with the setup call whenever it
  does. The `models` read is allowed at any time as well.
- **Alone in its answer.** The setup call is the sole call of the answer carrying it; beside
  other calls it is refused, since those would run on the model being left.
- **Once per message.** A message changes the chat's model at most once; a further setup call
  under the same message is refused — so no behaviour, `auto` included, can loop.

## Delegated turns

A delegated turn is configured as any chat and then follows the same design:

- **It starts on the setup of the turn that delegated**: its connection, model and effort, and
  its behaviour. The off-context agents — commit, test, match, prune, scan and the like — are the
  exception: the settings route them, and they recommend nothing.
- **The delegating turn may recommend first.** It has read the task it hands on, so its agent
  call may name the connection and model of the listing its subagent should run on. A setup that
  differs from the delegating chat's own is a recommendation of that chat — a lower, a raise or
  a switch against its own model — and passes its behaviour as any other: applied, or asked on
  the delegating chat's recommendation message before the subagent starts. Denied, the subagent
  starts on the delegating chat's setup.
- **The subagent may recommend again.** Its own session carries the assessment above its own,
  narrower context, and its setup call and its refused calls are recommendations of its own
  chat, under the behaviour it was started with. A recommendation it is asked on holds its turn
  there and shows as blocked in the chat that started it.
- **A permission** granted to a subagent is its own chat's: it does not switch the permission on
  in the chat that started it.

## Lower, raise and switch

| a recommendation of | is a |
|---|---|
| a model of the chat's family at a lower tier | **lower** |
| a model of the chat's family at a higher tier | **raise** |
| a model of another family, or one without a family or tier | **switch** |
| a permission | **raise** |

## Behaviour

| behaviour | a lower | a raise | a switch |
|---|---|---|---|
| `ask` | asked | asked | asked |
| `auto_lower` — the default | applied | asked | asked |
| `auto` | applied | applied | applied |

The behaviour is the `recommendations` of the settings, `auto_lower` without it, and a chat's own
choice stands over both. The chat's choice is made in two places showing the same value: the
behaviour control among the chat's setup controls, beside the permission switches, there at any
time — the one way out of `auto`, under which nothing is asked — and the drop-down of a
recommendation message.

## Applied and asked

- **Applied** at once, a recommendation leaves one line in the log naming the change and its
  reason (`model → haiku: a rename needs no more`), and the turn goes on.
- **Asked,** the turn is held on a recommendation message of the log: the recommended model or
  permission as a pill styled as the setup and permission pills — a click accepts it; the deny
  mark, the red cross in a circle — the setup stays; and the drop-down choosing the behaviour of
  this chat from then on.
- **An accepted model** takes the turn over where it stands: a new session of the conversation
  on the new setup, holding what the turn has done so far, goes on with the same message. A
  recommendation made in a session's first answer, before any work, costs nothing but that
  answer; a later one costs the prefix its cache, which the skill tells the model to weigh.
- **An accepted permission** is switched on for the chat and the held call applied.
- **Denied,** a model leaves the model told to go on and a permission leaves its call refused to
  the model; the same recommendation is not shown again in the conversation.
- **The security scan stands before a raise of permissions under every behaviour**, `auto`
  included: a finding holds the turn whatever would otherwise be applied.

## Contradictions

The assessment skill also has the model say, before it changes anything, where the message
contradicts a statement of its context. Similarity cannot find this — the reranker scored the
forbidding item 0.00 against the message asking for the forbidden — and the model answering reads
the statements anyway.

## What others do

Kept for the later evolution of this section; nothing of it is part of the design above. Surveyed
in November 2026; the figures are the sources' own and several are recent preprints.

The chosen design is the simplest of the kinds below — the model's own judgement under a default
skill, at any time of a session — beside what the harness already has: a subagent started on a
model its agent call names, and the off-context agents on the routes of the settings. The survey's
main caution is that **a model judges its own limits badly** (agents succeeding 22% of the time
predicted 77%, [arXiv 2602.06948](https://arxiv.org/abs/2602.06948)): a lower recommended by a
strong model is reliable, a raise recommended by a weak one is not, and no surveyed project makes
self-judgement its only trigger.

| mechanism | who decides | training data | mid-task | where |
|---|---|---|---|---|
| phase split — a strong model plans, a cheap one executes | fixed configuration | no | at the phase boundary | Claude Code [`opusplan`](https://code.claude.com/docs/en/model-config), Aider [architect/editor](https://aider.chat/2024/09/26/architect.html), Cline [plan/act](https://docs.cline.bot/core-workflows/plan-and-act), Roo modes |
| model by subagent — the top agent strongest, its subagents on lesser ones | configuration or the delegating model | no | at a subagent's start | Claude Code subagents, Roo; here the agent call's `model` |
| advisor tool — the cheap model stays and consults a strong one | the model, plus calls the harness forces | no | yes | Claude API [advisor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool.md) |
| failure counters — failed tests, failed edits, repeated calls | harness code | no | yes | OpenHands [stuck detector](https://github.com/OpenHands/software-agent-sdk/issues/762), which detects and changes no model |
| check of a finished answer, escalation when it fails | tests or a small judge model | none for tests | as a retry | [FrugalGPT](https://ui.adsabs.harvard.edu/abs/2023arXiv230505176C/abstract), [AutoMix](https://arxiv.org/abs/2310.12963) |
| start tier by rules over the prompt | local rules | no | per request | LiteLLM [complexity router](https://docs.litellm.ai/blog/heuristic-v2) |
| trained router over the prompt | a small classifier | yes | per request | [RouteLLM](https://lmsys.org/blog/2024-07-01-routellm/), Cursor, Copilot [Auto](https://docs.github.com/en/copilot/concepts/models/auto-model-selection), GPT-5, [Arch-Router](https://arxiv.org/abs/2506.16655v1) |
| router over a partial run or a failure | a fine-tuned model | yes | yes | [SWE-Router](https://arxiv.org/html/2607.00053v1), [CodeRescue](https://arxiv.org/html/2607.19338v1) |

What the survey suggests for a later step, in the order of its cost:

1. **A log of every recommendation with its outcome** — accepted or denied, and whether the turn
   then succeeded. It costs nothing and is what any threshold or trained router is fitted from.
2. **A raise by failure counters.** Consecutive failed runs, refused patches, identical repeated
   calls and rounds over a limit of the settings make the harness itself recommend a raise: no
   tokens and no self-judgement, the model's own setup call staying for a lower and a switch.
3. **A summary in place of the session on a raise.** Handing a stronger model the whole
   transcript recovered less than half of the quality gap in one study, a fresh start on the
   workspace state and a short summary more ([arXiv 2608.24358](https://arxiv.org/abs/2608.24358));
   a provider's cache is lost on a switch either way, which is why Copilot re-routes only at
   cache boundaries.
4. **An advisor call** in place of a raise: the chat's model stays and a stronger one returns
   short advice, forced by the harness before the first change and before the turn ends — a
   small model calls it reliably only when made to.
