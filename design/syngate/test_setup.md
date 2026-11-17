# Test setup

`syngate test` and `review` run pytest routines and Catch2 cases through two built-in branches told
apart by the routine's file suffix. The test setup makes the runner a property of the tree: an item
says how the routines bound under it are found, run and reported, so any suite a project builds —
forge, go test, cargo, jest, ctest, bats — runs under the same calls. No settings file is added: the
setup lives in the item's `test` key.

## The `test` key

| form | reads as |
|---|---|
| `enabled` / `disabled` | the switch of the subtree |
| `~`, a sha, a mapping `name: sha\|~` | the item's bindings |
| a **setup** mapping | `enabled`, with the setup of the subtree and, under `stamp`, the item's bindings |

```yaml
test:
  stamp: {deposit: ~, overdraw: 4be1…}   # what the key held before: ~, a sha, or name: sha|~
  run: forge test --junit --match-test ^({names:|})$
  files: [test/**/*.t.sol]
  report: junit                          # optional, detected without it
  env: {FOUNDRY_FUZZ_SEED: "0x01"}       # optional
```

- **`stamp`** holds the item's own bindings in the forms the key itself takes; without it the item
  has none and the setup mapping stands where the word `enabled` would. `review` writes the routine
  shas there.
- **Telling a setup from bindings.** A mapping is a setup when it holds `stamp`, or one of `run`,
  `files`, `report`, `env` with a value that is no binding value (a sha256 hex or `~`). `stamp` is
  refused as a binding name; a binding named `run` (the tree has two) stays a binding, and moves
  under `stamp` when its item takes a setup. An unknown key of a setup is a layout problem.
- **Where it may stand.** On any item where `test: enabled` or a binding may: the root, and below
  it any item not under one that switches the feature off — there it is the override nested in an
  override, as a binding is. Where the parents hand the feature off it switches it on (the own-key
  rule); where they hand it on it is the item's plain key and no repeated switch.
- **Scope.** A setup holds for its item and everything below, up to the next setup: unlike the
  switch it **may be nested**, a contracts folder under forge inside a tree under pytest. The
  nearest one wins whole — keys are not merged across setups. Any reconfiguration along a path
  is allowed and none is a layout problem: an item carrying no setup that its parents hand different
  ones takes its first parent's, and a run addressing a subtree runs every binding by the setup
  holding for its own item. Without any setup above, the built-in one below holds.
- **Review stamp.** The canonical JSON gains `"setup": {run, files, report, env}` only on an item
  carrying one, so every existing stamp stands and a changed command reads as *review violated* on
  its item. The leaves below are guarded by their routine shas, which a rebinding moves.
- **Who writes it.** `syngate edit <UID> --run CMD [--files GLOB …] [--report FORMAT] [--env K=V …]`,
  `--no-setup` removing it; the tree call `edit` takes the same as `setup: {…}`, under the Tree edit
  permission, an altering call of the security scan like every edit.

## Find: the tag

The bindings are tag pairs, so the routines must carry them in the source. In the `files` of a setup
(globs, root-relative, `**` for any depth) three forms are read:

- the pytest mark `@pytest.mark.syngate("UID"[, "binding"])`, in `*.py`;
- the Catch2 tags `"[UID][binding]"` of a test macro, in C and C++ sources;
- the **comment tag**, in any text file: a comment line ending in `syngate` + `:` or a blank +
  `UID` + optionally a blank and the binding — `// syngate: VAULT-DEPOSIT`,
  `# syngate: VAULT-WITHDRAW overdraw`, `/// @custom:syngate VAULT-DEPOSIT` (NatSpec takes custom
  tags only so). A closing `*/` or `-->` may follow.

For a comment tag the **routine** is what stands under it: its *head* is the first line below that
is neither blank nor a comment; its **name** is the first string literal of the head when that is
its first argument (`it("mints shares", …`), else the identifier in front of its first `(`
(`function test_Deposit(`, `func TestDeposit(t`, `fn deposit_mints(`); its **span** — what review
freezes — runs from the tag to the last line indented deeper than the head, a line of closing
brackets or `end` at the head's indent included. Several tags over one head bind it several times.
A head with neither a string nor a `(` is a layout problem of the binding.

*Exactly one routine per binding* is checked over the files of all setups together: a declared
binding no routine is tagged for is failed, red on its item. A tag whose UID names no item of the
tree binds nothing — it is passed over by discovery, the run and the report, and is no problem.

## Run: the selection

`run` is one command line, split into words as a shell splits them and **run without a shell** in the
project root, the `env` entries over the server's environment (a value `$NAME` passes a variable
through, so a key or an RPC URL is never written in the tree). The bindings addressed under one
setup are handed to it by placeholders, which is what makes the selection generic — every runner
selects differently, and each of those ways is a join of the same five facts:

| placeholder | one value per binding | serves |
|---|---|---|
| `{ids}` | `path::name` | pytest |
| `{names}` | the routine's name | forge, go, jest, cargo, ctest `-R` |
| `{tags}` | `[UID][binding]` | Catch2 |
| `{uids}` | the UID | a script of the project's own |
| `{paths}` | the routine's file, each once | runners taking files |

- **Joined.** `{names:|}` joins the values with the text after the colon inside the word it stands
  in: `--match-test ^({names:|})$`, `"{tags:,}"`. A word that is a bare plural placeholder —
  `{ids}` — becomes one word per value.
- **One by one.** The singular forms `{id}`, `{name}`, `{tag}`, `{uid}`, `{binding}`, `{path}`,
  `{line}` run the command once for each binding; a command mixing them with plural ones is refused.
- **Not at all.** A command with no selection placeholder runs the whole suite once, and only the
  results of the addressed bindings are taken. Always correct, and the slowest.
- `{report}` is a scratch file for a runner that writes its report to a path, `{root}` the project
  root. The same facts go by environment for a script: `SYNGATE_COVERAGE_FILE`,
  `SYNGATE_REPORT_FILE`, and `SYNGATE_SELECT_FILE`, a JSONL of `{uid, binding, tag, name, path, line}`.
- A command that cannot start — not on the PATH, not built — records every binding it was to run as
  failed with that reason, as the missing Catch2 binary does.

## Report: discovery

The result of a binding is searched in this order, the first source holding any result serving the
whole run of the command:

1. **Coverage JSONL** the run appended to `SYNGATE_COVERAGE_FILE` —
   the one format carrying the tag pair, joined directly.
2. **The `{report}` file**, then **the standard output**, in a format told by its content: JUnit XML
   (`<testsuite`), TAP (`ok` / `not ok` lines), CTRF (a JSON object with `results.tests`). `report`
   names the format only to overrule the detection.
3. **The exit status**, for a command run one by one: 0 is passed, the output its log.

A report of the second kind names tests, not tags, so it is joined through the names discovery
found: a result belongs to an addressed routine when its test name is the routine's name, or that
name followed by a `(…)` signature or a `[…]` parameter; where two addressed routines share a name,
the result's class or file must name the routine's file stem. Results of no addressed routine are
dropped. Several results for one binding all count, any failed one reddening the leaf; a skipped
test is failed, since it did not run; an addressed binding with no result is failed with `no result`
and the tail of the output.

## Built-in setup

With no setup above an item, the built-in behaviour holds and reads as two setups:

| | files | run |
|---|---|---|
| pytest | `tests/**/*.py`, `scripts/tests/**/*.py` | `<python> -m pytest {ids}` |
| Catch2 | `test/**/*.cpp` | `<build-dir>/<file stem> "{tags:,}"`, once per file |

both reporting by the coverage JSONL of the project's emitters.

## Modules

The setup is implemented by five modules, each the key source of the items stating it:

- `syngatelib.py` — the `test` key: `Item.setup` holds the item's own setup (`run`, `files`, `report`,
  `env`, absent keys left out) or None, parsed by `load_tree` and written by `dump_item`;
  `setup_scopes(items)` gives every item the UID of the item whose setup holds for it, None for the
  built-in one; `Location.routine` is the bare name of a routine.
- `testtags.py` — `comment_locations(root, globs)`: the comment-tagged routines of the files the
  globs match, `{(uid, binding): [Location]}`, and the problems of heads giving no name.
- `testselect.py` — `commands(run, bindings, root, report)`: the argument lists a `run` line expands
  to for the addressed bindings, each `{uid, binding, tag, name, path, line}`, with the bindings each
  one runs.
- `testreport.py` — `parse(text, format=None)`: the results of a JUnit, TAP or CTRF report, each
  `{name, classname, file, passed, log}`; `join(results, bindings)`: `{(uid, binding): [result]}`.
- `syngate.py` — `test` and `review` find the routines over the files of all setups, run each
  addressed binding by the setup holding for its item and record what the report discovery finds.
