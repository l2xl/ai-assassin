# CLI (`syngate`)

The tree calls (`add` / `edit` / `move` / `rename` / `delete`) are one line each over the core functions in
`syngatelib`; the AI Assassin UI and the Synthetic harness drive those same functions, so the command line
is their genuine spelling rather than a second implementation.

- `syngate add <UID> --parent <UID> [--dir syngate/<folder>] [--order N] [--description D]
  [--source PATH …] [--branch]` — scaffold an item (with a `test: ~` binding while the tree's test
  feature is on, which `--branch` withholds).
- `syngate edit <UID> [--description D] [--source PATH …] [--order N] [--run CMD [--files GLOB …]
  [--report FORMAT] [--env K=V …] | --no-setup]` — change an item in place, the `--source` list given
  replacing the item's; `--run` with its options writes the item's whole test setup, its bindings
  moving under `stamp`, and `--no-setup` removes it; with
  `--clear-review` an edit of anything under the stamp (description, parents, bindings, setup) drops
  its `review`, without it the stamp is left standing and the review reads as violated.
- `syngate move <UID> --to <UID> [--before <UID>] [--from <UID>] [--link]` — add and remove parent
  links and place the item among its siblings: `--from` names the link to re-point when the item
  has several, `--link` adds `--to` as one more parent instead of re-pointing, and a `--from` that
  is a parent while `--to` already is another drops the `--from` link.
- `syngate rename <UID> <NEW_UID>` — give an item a new UID: its file takes the new stem in its
  folder and every child's parent link follows it in place, a UID already taken — by an item or by a
  file of that stem, an unparsable one included — refusing it. The stamps of its parents and
  children move with it, dropped with `--clear-review`; test tags, coverage records and statements
  naming the old UID are left as they are.
- `syngate delete <UID>` — remove a childless item's file.
- `syngate query <UID>` — print the item as the AI reads it back: description, parents, sources,
  children in sibling order and kind, as JSON.
- `syngate context <UID>` — print the seed context an AI exchange anchored at the item is formed from.
- `syngate test <UID…> [--build-dir DIR] [--coverage-out FILE]` — run the routines bound to leaf
  items (literals or glob patterns) without stamping: pytest routines by node id in one process,
  Catch2 cases by an OR of their tag pairs in one run per test binary. With `--coverage-out` the
  run's records are folded into FILE, **replacing** the previous records of every re-run binding —
  with "any failed record reddens the leaf", an appended re-run could never turn a leaf green again.
  Runs whichever way the test feature sits: off only means the tree does not *await* tests of its
  items, so the routines tagged for them still run and still record coverage — with the switch off
  the bindings come from the discovered tags, since nothing is declared. Stamping stays `review`'s.
  A binding the run cannot execute — no or several tagged routines, test binary not built, a binding
  name the item does not declare — is recorded as failed with the reason; for a binding finding no
  routine the reason names the routines tagged for the item under its other bindings.
- `syngate review <UID…>` — **user-only**: validates the item, discovers its bindings, runs the bound
  tests, and stamps routine shas + `review` once every binding resolves to exactly one runnable
  routine — whether that routine currently passes or fails. A failing routine still freezes and the
  leaf simply rolls up as `test_failed` (TDD red state) until the implementation lands; only a
  binding that can't be run at all (ambiguous, unresolved, or not built) blocks stamping. `syngate clear
  <UID…>` removes the stamp (and reverts shas to `~`). Both take several UIDs and glob patterns in one
  invocation, a pattern expanding against the loaded tree — to leaf items for `review`, to stamped
  items for `clear` — and a pattern matching nothing rejected. Takes `--coverage-out` like `test`. Both
  refuse an item whose review feature is off, a pattern selecting only items that have it on, and
  `review` stamps an item holding `review: enabled` like any other, the stamp taking the word's place and `clear`
  putting the word back wherever the stamp was what switched the feature on; with the test feature off
  for it, `review` stamps a childless item without running anything. In a git work tree `review` stamps only over committed
  content: an item is refused, the files named, while its **review footprint** — what its statement
  is built from: the item files, key `sources` and linked project files of its seed context (its
  ancestors, itself and its descendants), and the files of the routines bound to it and to the items
  below it — holds a change git has not committed, modified, staged or untracked alike.
- `syngate validate [--coverage FILE …] [--strict]` — structural validation + frozen-routine checks
  (+ coverage join when given files; `--strict` requires every item reviewed that a review stamps). CI entry:
  Open Trader's `ci/gate.sh` (bootstraps `.venv-syngate` with this package; `GATE_STRICT=1` adds `--strict`).
- `syngate report [--coverage FILE …] [--out syngate_status.json] [--html <dir>]` — recursive status
  rollup + static HTML site.
