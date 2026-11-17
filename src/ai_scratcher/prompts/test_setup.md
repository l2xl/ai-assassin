---
kind: skill
description: How to put a project's own test suite — forge, go test, cargo, jest, ctest, bats or a script — under the tree through an item's test setup
---
# Test setup
Without a setup the tree runs two built-in suites: pytest routines marked `@pytest.mark.syngate("UID"[, "binding"])` in `tests/**/*.py` and `scripts/tests/**/*.py`, and Catch2 cases tagged `"[UID][binding]"` in `test/**/*.cpp`. Any other suite runs under the same `test` call once an item carries a **setup** saying how the routines bound under it are found, run and reported.

## The setup
Give it with the `edit` call, only where the user asks for it:
```syngate
[{"tool": "edit", "uid": "VAULT", "setup": {"run": "forge test --junit --match-test ^({names:|})$", "files": ["test/**/*.t.sol"], "report": "junit", "env": {"FOUNDRY_FUZZ_SEED": "0x01"}}}]
```
- `run` is required; `files`, `report` and `env` are optional. `"setup": null` removes it.
- It holds for its item and everything below, up to the next setup: setups may nest — a contracts branch under forge inside a tree under pytest — and the nearest one wins whole, no key merged from the one above. An item under no setup keeps the built-in suites.
- It switches the test feature on for its subtree, as a binding does, and is refused under an item that switches the feature off.
- It is part of its item's review: a changed command shows as a violated review on that item.

## Find: the tags in `files`
`files` are root-relative globs, `**` for any depth. Every routine of a leaf's binding carries its tag in the source, in one of three forms:
- the pytest mark, in `*.py`;
- the Catch2 tags of a test macro, in C and C++ sources;
- the **comment tag**, in any text file: a comment line ending in `syngate:` or `syngate` and a blank, then the `UID` and optionally a blank and the binding name — `// syngate: VAULT-DEPOSIT`, `# syngate: VAULT-WITHDRAW overdraw`, `/// @custom:syngate VAULT-DEPOSIT` (NatSpec takes custom tags only so). A closing `*/` or `-->` may follow.

A comment tag binds the routine standing under it. Its head is the first line below that is neither blank nor a comment; its name is the first string literal of the head when that is its first argument (`it("mints shares", …`), else the identifier in front of the head's first `(` (`function test_Deposit(`, `func TestDeposit(t`, `fn deposit_mints(`). Its span, what a review freezes, runs from the tag to the last line indented deeper than the head, a closing line of brackets or `end` at the head's indent included. Several tags over one head bind it several times; a head with neither a string nor a `(` is a layout problem.

Each declared binding needs exactly one tagged routine over the files of all setups together: one with none fails. A tag naming no item of the tree binds nothing and is passed over.

## Run: the selection placeholders
`run` is one command line split into words as a shell splits them and run **without a shell** in the project root, the `env` entries over the server's environment — a value `$NAME` passes a variable through, so a key or a URL is never written in the tree. The addressed bindings reach the command through placeholders:

| placeholder | one value per binding | serves |
|---|---|---|
| `{ids}` | `path::name` | pytest |
| `{names}` | the routine's name | forge, go, jest, cargo, ctest `-R` |
| `{tags}` | `[UID][binding]` | Catch2 |
| `{uids}` | the UID | a script of the project's own |
| `{paths}` | the routine's file, each once | runners taking files |

- **Joined:** `{names:|}` joins the values with the text after the colon inside the word it stands in — `--match-test ^({names:|})$`, `"{tags:,}"`. A word that is a bare plural placeholder, `{ids}`, becomes one word per value.
- **One by one:** the singular forms `{id}`, `{name}`, `{tag}`, `{uid}`, `{binding}`, `{path}`, `{line}` run the command once per binding; a command mixing singular and plural forms is refused.
- **Whole suite:** a command with no selection placeholder runs the suite once and only the addressed bindings' results are taken — always correct, the slowest.
- `{report}` is a scratch file for a runner writing its report to a path, `{root}` the project root. A script gets the same by environment: `SYNGATE_COVERAGE_FILE`, `SYNGATE_REPORT_FILE` and `SYNGATE_SELECT_FILE`, a JSONL of `{uid, binding, tag, name, path, line}`.
- A command that cannot start — not on the PATH, not built — fails every binding it was to run, with that reason.

## Report: where results are read
The first source holding any result serves the whole run:
1. the coverage JSONL the run appended to `SYNGATE_COVERAGE_FILE`, which carries the tag pair itself;
2. the `{report}` file, then the standard output, as JUnit XML, TAP or CTRF told by its content — `report` (`junit`, `tap`, `ctrf`) only overrules the detection;
3. the exit status, for a command run one by one: 0 passes, the output is the log.

A JUnit, TAP or CTRF result belongs to an addressed routine when its test name is the routine's name, or that name followed by a `(…)` signature or a `[…]` parameter; where two addressed routines share a name, the result's class or file must name the routine's file stem. Several results of one binding all count, any failed one failing it; a skipped test fails, since it did not run; a binding with no result fails with `no result` and the tail of the output. So pick a runner output that names tests the way their heads do, and a `run` line that prints or writes one of these formats.

## Steps
1. Tag every routine of a changed leaf in its source, in the form its language takes.
2. Give the subtree's item a setup whose `files` cover those sources and whose `run` selects by the placeholder the runner accepts.
3. Run the `test` call on the leaves; a `no result` failure means the report or its names do not reach the routines — fix the `run` line or `report`, not the leaf.
