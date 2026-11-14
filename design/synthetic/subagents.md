# Subagents

Every LLM session the harness runs is a **subagent**: the turn a user's message starts, the turn
another turn delegates, the commit the status popup asks for, the scan the harness runs by itself.
There is one way to run a session — through the harness — and two kinds of session, told apart by
what stands above the start message:

| kind | system prompt | start message | where it runs |
|---|---|---|---|
| **DAG-bound** | the seed context of an item | only what the tree does not hold | that item's chat |
| **off-context** | an agent of the prompt library, alone | the request | the chat it was started from |

This replaces the earlier split into explicit delegation and observed implicit subagents: a session whose prompt a model wrote freely, above no seed
context, was an off-context agent nobody had defined.

## DAG-bound subagents

The task of a DAG-bound subagent is its item's statement and the briefing is the item's seed
context, so its start message stays as short as the tree allows — none at all for a delegation, the
standing instruction to carry out the statement standing in, and bounded where one is given. Work
that no item states yet gets its item first: the task routing skill adds it, with a semantic UID and
the request condensed into its statement, and the subagent is started there — the request thus
enters the session as part of the seed context rather than as a prompt, and stays in the tree
after the session.

## Start points

An off-context subagent starts from any of four places, the run being the same:

- **the page** — `⎇ Commit with AI` of the status popup starts the commit agent;
- **the orchestrator** — a message matched to an agent runs it in place of a DAG turn;
- **the harness itself** — the verdict agents of its own steps;
- **an answer** — `{"tool": "agent", "name": "explore", "prompt": "…"}`, the agent call naming an
  agent instead of an item; its report comes back as an item-bound call's does, `background`
  included.

## Cover of an off-context run

An off-context agent never runs with less than its lists, and its prompt names no `modes`: before
its run the chat it is started from must offer every tool and skill the lists name — `git` is not
offered while no work tree is at hand — and have on every permission its tools need: `tree` for
`syngate_api`, `patch` for `patch`, `bash` for `shell`, `websurf` for `websurf`; the other tools
need none. Both starts that run a named agent — the agent call and the orchestrator's match — make
this check before the run; the lists themselves are never cut to what the chat has.

- **What the chat does not offer forbids the run:** a tool or skill the library at hand lacks, or a
  permission the connection the agent is routed to does not list.
- **A permission the chat has off is asked** in that chat as the recommendation to switch it on
  ([setup_recommendation.md](../orchestrator/setup_recommendation.md)): applied at once under the
  behaviour `auto`, else the starting turn is held until the user answers, and a granted one is on
  for the chat from then on.
- **A denial forbids the whole run**, and so does a permission denied before in the conversation:
  it stops before any turn of the agent starts. Once running, a listed tool does what the
  permissions of the starting chat let it do.

## Where a subagent shows

A subagent is shown in the chat it was started from: an agent step with its indicator while it
runs and, once it ends, its report and transcript as an agent message. A DAG-bound one is besides a
turn of its own item's chat, and its indicator in the starting chat is the link jumping there; an
off-context one has no chat of its own and its transcript lives in the starting chat alone. A verdict
agent shows as a step of the harness — what it was asked and what it answered — never as a message.

## No sessions outside the harness

A connector that could launch sessions of its own is denied the means: the Claude Code connector
runs with its `Agent` and `Task` tools denied in every mode, as it runs with its edit tools denied. The
delegation skill accordingly tells a turn to hand work on through the agent call alone — by item
for work an item states, by name for an agent — and the transcript attachment of observed
subagents has nothing left to attach.
