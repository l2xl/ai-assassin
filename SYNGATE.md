# Synergy Context Gate (Syngate)

The subsystem managing a project's DAG of statements, their test coverage and review status as a
gate: open while every status passes, closed by anything failed. It holds the project model — the
DAG and the design documents its items link — the test binding, the review freeze and the status
rollup, as the `syngatelib` library, the `syngate` CLI, `check_self_approval` and
`render_syngate_report`. The whole of AI Assassin, which Syngate is one part of, is introduced in
[README.md](README.md).

# Tree Model

- **Any `*.yml` file under any `syngate/` subfolder is one item.** The UID is the file stem
  (`INFRA-066.yml` → `INFRA-066`), globally unique. Folders are external sorting only — moving a
  file between folders changes nothing. Other extensions (`.md`, …) are ignored by tooling.
- **The tree shape lives inside the items** via `parents`. Multi-parent items form a DAG; exactly
  one item has empty `parents` (the root, `OPEN-TRADER`). No settings files anywhere.
- **The rules the items follow are the default skill** [syngate.md](src/ai_scratcher/prompts/syngate.md),
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
  the commands of that feature refuse to run and the page shows none of its affordances; with the
  test feature off, `review` stamps childless items as approved text. AI Assassin's own root
  (`AI-ASSASSIN`) and Open Trader's (`OPEN-TRADER`) switch both on.

# Item Schema

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
  the seed context of every exchange anchored at the item, above or below it (see
  [SYNTHETIC.md](SYNTHETIC.md)), each once, so a file listed by an ancestor is not listed again.
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
  record of user approval. On the root item, `enabled` / `disabled` is the tree's review feature
  switch instead.
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

# Test Binding

Binding identity is the tag pair; the routine's location is *discovered* from tags at check time,
never declared in items — tests move freely between files without touching `syngate/`.

- **Pytest** (`scripts/tests/`, `tests/`): `@pytest.mark.syngate("INFRA-066")` for the default binding,
  `@pytest.mark.syngate("INFRA-066", "binding_name")` for a named one. Discovered by an `ast` scan.
- **Catch2** (`test/`): `TEST_CASE("…", "[INFRA-066]")` or `…[INFRA-066][binding_name]`.
  Discovered by a source scan for test macros; the binding name is the tag immediately following
  the UID tag, so place item tags last.
- Each binding must resolve to **exactly one** routine; 0 or >1 is a gate error on reviewed items.
- **Routine hash**: sha256 of the routine's raw source span (pytest: decorators through the end of
  the function; Catch2: the TEST_CASE line to the next test macro or EOF). Shared-fixture changes
  outside the span are consciously not tracked.

# Coverage JSONL

Test executions self-report which bindings ran: one JSON line
`{"tags": ["INFRA-066", "binding_name"], "passed": true, "name": …, "log": …}` appended to the
file named by `SYNGATE_COVERAGE_FILE` (no emission when unset).

- Emitters live in the managed project: a pytest `conftest.py` hook (see `tests/conftest.py` here)
  and, for Catch2, a listener linked into every test executable (Open Trader's
  `test/syngate_coverage_listener.cpp`).
- The gate joins records against `test:` in both directions: every reviewed leaf binding needs ≥1
  executed record, and every record's UID must match a known item.

# CLI (`syngate`)

The tree calls (`add` / `edit` / `move` / `delete`) are one line each over the core functions in
`syngatelib`; the AI Assassin UI and the Synthetic harness drive those same functions, so the command line
is their genuine spelling rather than a second implementation.

- `syngate add <UID> --parent <UID> [--dir syngate/<folder>] [--order N] [--description D]
  [--source PATH …] [--branch]` — scaffold an item (with a `test: ~` binding while the tree's test
  feature is on, which `--branch` withholds).
- `syngate edit <UID> [--description D] [--source PATH …] [--order N]` — change an item in place,
  the `--source` list given replacing the item's; with `--clear-review` an edit of anything under
  the stamp (description, parents, bindings) drops its `review`, without it the stamp is left
  standing and the review reads as violated.
- `syngate move <UID> --to <UID> [--before <UID>] [--from <UID>] [--link]` — add and remove parent
  links and place the item among its siblings: `--from` names the link to re-point when the item
  has several, `--link` adds `--to` as one more parent instead of re-pointing, and a `--from` that
  is a parent while `--to` already is another drops the `--from` link.
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
- `syngate review <UID>` — **user-only**: validates the item, discovers its bindings, runs the bound
  tests, and stamps routine shas + `review` once every binding resolves to exactly one runnable
  routine — whether that routine currently passes or fails. A failing routine still freezes and the
  leaf simply rolls up as `test_failed` (TDD red state) until the implementation lands; only a
  binding that can't be run at all (ambiguous, unresolved, or not built) blocks stamping. `syngate clear
  <UID>` removes the stamp (and reverts shas to `~`). Takes `--coverage-out` like `test`. Both are
  refused while the tree's review feature is off; with the test feature off, `review` stamps
  childless items without running anything.
- `syngate validate [--coverage FILE …] [--strict]` — structural validation + frozen-routine checks
  (+ coverage join when given files; `--strict` requires every item reviewed). CI entry:
  Open Trader's `ci/gate.sh` (bootstraps `.venv-syngate` with this package; `GATE_STRICT=1` adds `--strict`).
- `syngate report [--coverage FILE …] [--out syngate_status.json] [--html <dir>]` — recursive status
  rollup + static HTML site.

# Status Rollup

Two independent axes per item (`compute_axes`; what the UI shows):

- **Test**: `unknown` | `test_passed` | `test_failed`. Leaf: any failed record → failed; any binding
  without a record → unknown; else passed. Branch: the worst of its children and its own bindings,
  if it carries any — a failed item fails every ancestor, else one unknown item leaves them
  unknown (the page shows `unknown` as `not run`). The axis reflects the run records alone — a violated review never reddens it. A run that cannot execute a binding (no or several tagged
  routines, test binary not built) records it as failed — a test that cannot be found is red.
- **Review**: `not_reviewed` | `reviewed` | `review_violated`. The worst of an item's own stamp and
  its children's axes: a branch is reviewed when it and everything below it is. An item's own
  validation problem (stale stamp, drifted frozen routine, malformed item) is a violated review;
  violated outranks not reviewed, which outranks reviewed. A branch's stamp covers its statement,
  parents and the list of its children, so editing a branch or adding a child under it clears it.
  A problem is attributed to the item it names and reaches only that item's ancestors — never the
  item whose tooling detected it, and never the whole tree: a coverage gap is not an item problem,
  since one missing coverage file would otherwise redden every reviewed leaf at once.

The single-status rollup below (`compute_status`) is what `syngate report`, the CI summary and the
check run still publish; SYNGATE-LEAF-STATUS and SYNGATE-BRANCH-STATUS define it, so retiring it in favour of the axes is a
user decision.

Leaf: no executed records → `not_implemented`; any failed record → `test_failed`; all bindings
covered and passing → `test_passed`; some covered → `partially_implemented`. A childless item
without a `tests` key has no bindings to cover, so it rolls up as `not_implemented` the same way.
Branch: aggregate of children (any failed → failed; all not_implemented → not_implemented; all
passed → passed; else partial).

**Validation problems redden the item they name, never the item that found them.** A stale review
stamp, a drifted frozen routine or a malformed item is a defect of *that* item: `item_problems`
attributes it by UID, `compute_status` marks the item `test_failed`, and it rolls up through that
item's own parents only. An item whose bound test detects such a violation is working, so it
stays green — the tooling's own tests assert tooling behaviour against fixtures, and where they read
the live tree (`SYNGATE-TREE-LAYOUT`) they assert its *layout* (`validate_layout`), not its review state.
Coverage gaps are deliberately not item problems: an unrun binding already rolls up as
`not_implemented`, and one missing coverage file would otherwise redden every reviewed leaf at once.

# Process Rules (TDD gate)

- **Test-first, then freeze.** The covering routine is tagged with the leaf's UID before
  implementation; the user approves via `syngate review`, which freezes the routine by hash while it is
  still red — approval fixes *which* routine and *what it says*, not whether it already passes.
- **Frozen routines are immutable.** Editing a reviewed leaf's bound routine reddens the gate until
  a user-approved `syngate clear` + re-review.
- **Two-commit re-approval** (`check_self_approval.py`, Open Trader CI `approval` job): a commit that
  changes an item's approval may neither change the item's substance nor touch any file under the
  test trees.
- **CI flow** (Open Trader `.github/workflows/validate.yml`): build → ctest (emits
  `build-ci/syngate_coverage.jsonl`, uploaded as `syngate-coverage-cpp`) → syngate job: `gate.sh`,
  pytest (emits `pytest-coverage.jsonl`), coverage join via `gate.sh --coverage …`, `syngate report`,
  job summary + `Syngate Status` check run.
- **A red gate never costs the report.** The gate's verdict decides the job's colour, not whether
  the run is reported: every report step runs on `!cancelled()`, and `gate.sh`'s output (`gate: OK`
  / `gate: FAILED`) is captured into `syngate_validate.log` and folded into the top of both the job
  summary and the check run, so the reason for the red is read off the report itself.
