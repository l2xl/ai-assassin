# Tree model

- **Any `*.yml` file under any `syngate/` subfolder is one item.** The UID is the file stem
  (`INFRA-066.yml` → `INFRA-066`), globally unique. Folders are external sorting only — moving a
  file between folders changes nothing. Other extensions (`.md`, …) are ignored by tooling.
- **The tree shape lives inside the items** via `parents`. Multi-parent items form a DAG; exactly
  one item has empty `parents` (the root: `AI-ASSASSIN` here, `OPEN-TRADER` in Open Trader). No settings files anywhere.
- **The rules the items follow are the default skill** `syngate.md` of the prompt library,
  which heads every seed context: one testable thesis per leaf, design detail in linked files, each
  linked once, `sources` for key source files only, which branches earn their place, the shape of a
  statement and the naming of UIDs. They are stated there once and not repeated here.
- **Leaf vs branch is structural**: a branch has children; a `test` key binds tests to the item
  that carries it — every implemented leaf, and any branch that has tests of its own. A
  test-bearing branch passes only when its own bindings and all its children pass, and it is
  reviewed and frozen exactly as a leaf is. A childless item without `test` is simply not yet
  implemented — it rolls up as `not_implemented` like any leaf with no coverage.
- **The root item switches the tree's features.** `test: enabled` turns test binding on and
  `review: enabled` turns review stamping on; both are **off when absent**, so a project that wants
  neither the TDD gate nor approval stamps carries plain items only. A root's own binding or stamp
  switches its feature on as well. With a feature off, an item carrying its key is a layout problem,
  the commands of that feature refuse to run, naming the switch to set (`review: enabled`), and the
  page shows none of its affordances; with the test feature off, `review` stamps childless items as
  approved text, and with it on, an item without a binding of its own is stamped without a run. AI Assassin's own root
  (`AI-ASSASSIN`) and Open Trader's (`OPEN-TRADER`) switch both on.

## Item schema

An item file is a YAML front matter of attributes over a markdown body:

```markdown
---
parents: [INFRA-065]
order: 10
sources: [ci/build.sh, .github/workflows/validate.yml]
test: ~
review: <sha256 hex, present only after user review>
---
CI build on push

The CI pipeline builds the project on every push to the repository.
```

- The body is the item's **statement** (`description`), in markdown, shaped as the skill states.
  There is no separate header: the body's **first line** is what the outline shows as the item's
  **title**, cut with an ellipsis where the row runs out of room, while the content panel renders
  the whole body as a section of one document under its ancestors.
- `sources` — optional list of root-relative paths of the item's **key source files**. They enter
  the seed context of every exchange anchored at the item, above or below it, each once, so a file listed by an ancestor is not listed again.
  Outside the reviewed stamp.
- `order` — optional, presentation-only sibling sort key; siblings sort by `(order, UID)`.
  Excluded from the reviewed stamp: reordering a report never triggers re-review.
- `test` forms: `~` → single default test bound by the `[UID]` tag alone (becomes
  `test: <routine-sha256>` once reviewed); mapping `name: sha|~` → each binding bound by the
  `[UID][name]` tag pair. Binding names: `[a-z0-9_]+`, unique per item. On the root item,
  `enabled` / `disabled` is the tree's test feature switch instead.
- `review` — transparent stamp: sha256 hex over the canonical JSON
  `{"children":[…],"description":…,"header":…,"parents":[…],"tests":{name:sha}|null}` (`sort_keys`,
  compact separators, UTF-8; default binding name `""`, unstamped shas `""`). `header` is the body's
  first line and `description` the rest past one blank line — the two fields the body was before —
  so the stamps of that time stand. `children` holds the
  immediate child UIDs and is present only for an item that has any, so a childless item's stamp is
  unchanged and adding or removing a child moves its parent's. Recompute with
  `syngatelib.item_stamp(items, uid)`, or `compute_stamp` plus the child set. Stamping is **user-only** — the stamp is the
  record of user approval. A `review` value that is not a sha256 hex reads as no stamp, never as an
  error. On the root item, `enabled` / `disabled` is the tree's review feature switch instead.
- A call that moves stamped content settles the stamps it touched one of two ways. With
  `--clear-review` — the page always passes it, and it is yours to pass from the CLI — the stamp is
  dropped and the item reads as *not reviewed*. Without it, as when a call is proxied from an AI
  answer or a file is edited behind the tooling, the stamp is left standing over content that no
  longer matches it and the item reads as *review violated*, so an unattributed change is loud
  rather than quietly unapproved.
- A legacy item is one flat YAML mapping holding `header` and `description` as keys next to the
  attributes; its header reads as the first line of the body, and the old spellings `tests` and
  `reviewed` are read as `test` and `review`, so an existing tree keeps loading. The canonical
  writer emits the front-matter shape with `test` and `review`, so items migrate as they are
  edited. A front matter carrying `header` or `description` is refused: they are the body.
