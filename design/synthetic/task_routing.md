# Task routing

**Task routing.** The task routing skill, a default one too, moves a request for a change to
the item whose context fits it best — the anchored item, an item of its seed context, or one the
exchange names by `@UID` — and, where no item states the facility yet, has the model add it
first, with a semantic UID and a statement condensed from the request. The task then goes on as
an `agent` call to that item rather than as an implicit subagent: only the harness's own turn is
seeded with the target item's context, and the delegated turn is a turn of that item's chat, shown
there live. Only when the fit is the anchored item does the turn keep the work, and a question or
a discussion asking for no change stays in the anchored chat. The extraction
marks of the chat are this routing started by hand, the parent named
by the mark.
