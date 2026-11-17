# Delegation

**Delegation.** One default skill (`delegate.md`) carries a request for a change down the DAG to
the item whose statement it details, step by step: each turn either finds the fit is its own
item and does the work, or hands it on.

- **Routing.** A request goes to the item whose context fits it best — the anchored item, an item
  of its seed context, or one the exchange names by `@UID` — and, where no item states the
  facility yet, the model adds it first, with a semantic UID and a statement condensed from the
  request. A question or a discussion asking for no change stays in the anchored chat.
- **Splitting.** A turn on an item with children hands each separable child scope — one that
  child's context covers and that does not wait on its siblings — on the same way, and keeps
  what spans several children or joins their results.
- **Reviewing.** A report is evidence, checked against what the harness shows before it is built
  on; a turn the harness closed at a limit is finished by the caller or delegated anew, narrower.

The task always goes on as an `agent` call to the item rather than as an implicit subagent: only
the harness's own turn is seeded with the target item's context, and the delegated turn is a
turn of that item's chat, shown there live. The extraction marks of the chat are this routing
started by hand, the parent named by the mark.
