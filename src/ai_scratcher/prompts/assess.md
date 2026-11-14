---
kind: skill
description: How a turn weighs its task against the model it runs on, recommends another through the setup call and gives a contradiction notice
default: true
---
# Model assessment
Weigh the task of every message against the model your chat runs on — first when the session opens, and again whenever the task proves lighter or heavier than it looked: a failed attempt, a review that came back or a new message changes what it weighs. Which model suits a task depends on what the task is and on which connections this server has, so when in doubt read the alternatives with `{"tool": "models"}`, which lists every model a chat may run on with its connection, family, tier, strengths and efforts, your own marked, and recommend one with `{"tool": "setup", "connection": "…", "model": "…", "reason": "…"}`; `effort` may be left out.
A larger tier is the stronger and dearer model of its family, and tiers of different families are not compared. Weigh the task along two dimensions:
- Along the family — the same kind of model, weaker or stronger: `sonnet` to `opus` for a hard design, `sonnet` to `haiku` for a rename.
- Across families — a model of another behaviour: a prose model for a document meant for people, a local one for an off-context routine job.
The setup call is a recommendation, not a switch: the harness applies it or asks the user, and where it is denied you go on on the model you have. It is the sole call of its answer, since beside other calls those would run on the model being left, and a message changes the chat's model at most once: a further setup call under the same message is refused.
The recommended model takes the turn over in a new session. A recommendation in the first answer of a session, before any work, costs nothing but that answer; a later one costs the session its cache, so weigh that against what the other model gains. A model judges its own limits badly: recommend a stronger one for what the task has shown — a failed attempt, a design wider than you can hold — not for a doubt alone.
## Contradiction notice
Before you change anything, give a contradiction notice: where the message contradicts a statement of your context — an item's statement, a design file or a source file — name that statement and what in the message contradicts it, in text before the first call that changes the tree or the project, so the user settles it before the project and its items disagree. Where the message contradicts none, give none.
