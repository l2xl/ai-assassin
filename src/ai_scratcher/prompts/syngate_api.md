---
kind: tool
description: Read and change the syngate tree and run the tests bound to its items
calls:
  add:
    required: [uid, description]
    optional:
      parent: {type: string}
      sources: {type: array, items: {type: string}}
      kind: {enum: [leaf, branch]}
  edit:
    required: [uid]
    optional:
      description: {type: string}
      sources: {type: array, items: {type: string}}
      tests: {type: array, items: {type: string}}
      setup:
        anyOf:
          - type: object
            properties:
              run: {type: string}
              files: {type: array, items: {type: string}}
              report: {enum: [junit, tap, ctrf]}
              env: {type: object, additionalProperties: {type: string}}
            required: [run]
            additionalProperties: false
          - type: "null"
  remove:
    required: [uid]
  move:
    required: [uid, to]
    optional:
      before: {type: string}
      from: {type: string}
      link: {type: boolean}
  rename:
    required: [uid, new_uid]
  query:
    required: [uid]
  context:
    required: [uid]
    optional:
      label: {type: string}
      for: {type: string}
  test:
    required: [uid]
    optional:
      name: {type: string}
---
# Syngate API
The files under syngate/ are closed to your file tools, to read as to write: the tree is read and changed only through these calls.
```syngate
[{"tool": "query", "uid": "@"},
 {"tool": "context", "uid": "AREA-010", "label": "item to split"},
 {"tool": "add", "uid": "AREA-030", "parent": "@", "description": "…", "sources": ["src/area.py"], "kind": "leaf"},
 {"tool": "edit", "uid": "@", "description": "…", "sources": ["src/area.py", "docs/AREA.md"], "tests": ["api", "page"]},
 {"tool": "remove", "uid": "AREA-020"},
 {"tool": "move", "uid": "AREA-010", "to": "AREA", "before": "AREA-030"},
 {"tool": "rename", "uid": "AREA-030", "new_uid": "AREA-STATUS"},
 {"tool": "test", "uid": "AREA-010", "name": "binding"}]
```
"@" stands for the anchored item; any other item is addressed by its UID, the stem of its file under syngate/.
The chat's Tree edit permission decides whether add, edit, move, rename and remove are applied — query and context always are; while it is off they are refused and the refusal comes back as your next prompt: answer in text and say what you would change.
- query: read an item back — description, parents, sources, children in sibling order, kind and a leaf's test bindings. Query the parent before adding under it, to pick a free UID and the place among its children.
- context: read the seed context of an item, as an exchange anchored at it is seeded: the item's own statement stands under `@UID (active item)`. The item you read is usually not the one you are anchored at, so name a `label` — one line saying what the item is to this reading (`item to split`, `candidate parent`) — to mark its statement so instead; the label keeps the context you read from passing for your own, whose active item is the one your seed context marks. The files of a large context may come as their path and line count alone: `for` names in a line what you read the item for, the files then being weighed against it rather than against your message; read a file held back with the files tool.
- add: a new item under `parent` (default "@") with its `description` — the statement, written by the DAG rules — and optionally its `sources`, the root-relative paths of the key source files that enter the seed context of every exchange anchored at the item, above or below it; `kind` "leaf" (default) carries a test binding, "branch" does not.
- edit: the `description`, `sources` and/or `tests` of an item; a given `sources` list replaces the item's, a given `tests` list replaces a leaf's test bindings by their names — `[""]` the default one, bound by a routine tagged with the UID alone, else names in lowercase letters, digits and underscores, each bound by a routine tagged with the UID followed by the name. A given `setup` — `{"run": …, "files": […], "report": …, "env": {…}}`, `run` required, or `null` removing it — replaces the item's test setup: how the routines bound under it are found, run and reported; give one only where the user asks for it, and load the `test_setup` skill for its tag forms, placeholders and reports.
- remove: a childless item.
- move: under parent `to`, in front of sibling `before` (default last). `from` names the parent link to re-point when the item has several; `link` true adds `to` as one more parent instead of re-pointing, and a `from` that is a parent while `to` already is another drops the `from` link.
- rename: give the item the UID `new_uid`; its file and every child's parent link follow it, while test tags and statements naming the old UID stay as they are.
- test: run the routines bound to the leaves under the item, `name` narrowing a leaf to one binding. Every test call of a batch joins one run, performed after the other calls. The outcome comes back as one line per leaf binding with pass/fail, then the output of every failed routine or, for a binding the runner could not run, its reason. Review stamping is the user's act: there is no review call.
  - A UID addresses the item and every leaf below it, each run by the setup it stands under: `@` runs your own item's, and the narrowest item holding what you changed is the call to make — an item above it runs every suite under it, the slow ones included. A glob matches UIDs by their text over the whole tree, never a subtree: `AREA-*` also takes the items elsewhere named so, those awaiting no tests among them, which fail for want of a routine. Use a glob only for leaves no one item holds.
  - The runner is one for the server: a run live elsewhere — the user's in the page, a subagent's beside yours — refuses the call. That is no result of the tests: send the call again in a later round, and where you delegate in parallel, tell which turn runs the tests.
  - Read a failure by its reason before changing anything. `must match exactly one routine, found: none` is a tag missing or not in the form its file takes, `no result` a run line or a report that does not reach the routine: the `test_setup` skill states both forms, so load it rather than trying tag spellings, and never rename an item or a routine to make a binding resolve. A failure every binding of a run shares — a command not found, a dependency not installed, a build missing — is the environment's, not the leaves': report it, with the command that would mend it, instead of reworking the tests.
A call of yours never clears a review stamp: every stamp it moves -- the item's own, and its parents' where their child set changed -- is left standing over content that no longer matches it, so the change shows up as a violated review for the user to settle. Only the user's own edit in the page clears a stamp.
The test and review features are set per subtree: the root switches them, `test: enabled|disabled` or `review: enabled|disabled` on an item below sets one for that item and everything under it, once per path, and a binding or a stamp on an item whose parents have the feature off switches it on the same way. So `tests` given by `edit` to an item whose test feature is off make it the item its subtree is tested from: do that only where the user asks tests of that subtree, and take the refusal under an item that switches the feature off as final. The switch words are the user's to write.
