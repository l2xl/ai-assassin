# Agent tool

**Explicit delegation, harness-controlled.** `{"tool": "agent", "uid", "prompt", "model",
"effort", "modes"}` runs a turn of the named item's chat, anchored there with that item's own seed
context. That statement and seed context are the whole briefing: without a `prompt` the turn
starts with the standing instruction to carry out the item's statement and report
(`synthetic.DELEGATION_TEXT`); a `prompt` only adds a detail the tree does not hold, and one past
300 characters is refused as restating the task, the parent putting what the statement lacks into
it with `edit` instead — so a delegation never pays twice for context the tree already carries.
Every `agent` call of a batch runs in parallel after the batch's other calls, the parent
turn awaits them, and their final reports come back as the next prompt the way query results do;
a busy item refuses the call, since an item runs one turn at a time. The subagent is an ordinary
turn of the child's chat, so its whole transcript is where the child is shown. A call marked
`"background": true` is not awaited: it is answered at once with `- agent UID: started in the
background (turn UID:n)`, the parent turn goes on and may end while the child runs, and the
child is stopped by a stop of the parent only while the parent runs. When the child ends, its
report and transcript join the parent's chat as an agent report message and wait among the chat's
unreported reports — kept with the chat across restarts — to head the next message the user
sends, in a conversation with a session; without one the kept history carries them. The delegation
skill, a default one, tells the model to analyse the scope of an item with children — reading them
with `query` — and to delegate the separable ones this way. This is the preferred form.

*Designed, not implemented:* `{"tool": "agent", "name": "explore", "prompt": "…"}` names an agent
of the prompt library instead of an item and runs that off-context subagent; its report comes back as
an item-bound call's does, `background` included.
