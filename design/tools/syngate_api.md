# Syngate API tool

**Tree calls are the only way the agent touches the DAG.** The model never opens the files under
`syngate/` — the Claude Code connector denies `Read`, `Edit` and `Write` under `syngate/**` in
every mode, a shell command reading there refused the same way.
`"@"` stands for the anchored item, every other item is addressed by its UID:
`{"tool": "add", "uid", "parent" (default "@"), "description", "sources", "kind": "leaf"|"branch"}`
adds a statement last among its parent's children, in the folder of its last sibling (else the
parent's); `{"tool": "edit", "uid", "description", "sources"}` changes one, a given `sources` list
replacing the item's; `{"tool": "remove", "uid"}` drops a childless statement;
`{"tool": "move", "uid", "to", "before" (default last), "from"}` re-points the parent link and
places the item, `from` naming the link when the item has several parents. The harness runs the
calls in order through `add_item`, `edit_item`, `delete_item` and `move_item` and stops at the
first refused one: the refusal goes back to the model as its next prompt with the results of the
calls applied before it, so the model corrects the call or answers in text. The history shows
every batch with what it applied, read or had refused, every call a block of the chat's log; the
reply is the model's own text alone, never a line of the calls. What was
applied, ran or was reported — each repeated line once, with its count, never what was read — goes
only where a model reads the outcome without the log: the report a delegating turn receives and the
history a new session starts from; the user reviews the result as any other edit.

**Queries read the DAG back the same way.** `{"tool": "query", "uid"}` returns the item's
description, parents, sources, children in sibling order and kind; `{"tool": "context", "uid"}`
its seed context, its item marked as the active item or, with the optional `label` the call names, as that label says, so a context read for another item is not taken for the exchange's own; `{"tool": "skill", "name"}` the named skill. What a batch read goes back into
the same session as the next prompt and the exchange continues with the next answer, for as many
rounds as the work needs: the round fuse — `orchestrator.rounds` of the server settings, else
`synthetic.QUERY_ROUNDS` (100) — or `websurf.rounds` (`websurf.ROUNDS`, 40, without one) once the
turn has surfed, and the stall breaker end it by what the harness observes, the results prompt
naming the rounds left once `synthetic.ROUNDS_WARNING` or fewer remain; a turn so ended is asked for
a closing report and refused only when it answers that with calls (turn_limits.md).

**Test runs go through the page's runner.** `{"tool": "test", "uid", "name"}` runs the routines
bound to the leaves under the item, `name` narrowing a leaf to one binding (the CLI spelling
`syngate test UID:binding`); every `test` call of a batch joins one run after the batch's other
calls. It is the same single-flight runner as `▶ Run test` — the records land in the run coverage, the
statuses recolor, a run live elsewhere refuses the call — and its outcome comes back like a
query's result: one line per leaf binding with pass/fail, then the output of every failed routine.
Review stamping stays the user's act: there is no review call, and a tree call of the AI never
clears a stamp — it is left standing over the changed content, a violated review for the user to
settle.
