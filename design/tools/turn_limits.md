# Turn limits

A turn runs for as many rounds as its work needs: the reads, the edits and the test runs of a real task are many
rounds, and a count of them cannot tell a stuck loop from work. The harness therefore ends a turn by what it
observes, never by a small count, and a turn it ends still reports.

- **Round fuse.** `orchestrator.rounds` of the server settings, 100 without it (`synthetic.QUERY_ROUNDS`), bounds
  the rounds of a turn that has not surfed; a turn that has surfed keeps `websurf.rounds`. It is a backstop set far
  above normal work, a fuse and not the control: the results prompt names the rounds left once few remain.
- **Stall breaker.** A round whose calls and results equal those of the round before is no progress. The first
  such repetition is told to the model with its next prompt, a nudge to change what it does or to answer; the
  second closes the turn. A hard stop on the first sign would end turns a nudge recovers.
- **Closing report.** A turn the harness closes -- at its fuse or stalled -- is not failed at once: its next prompt
  carries the results as usual and asks for one last answer in text, what was done, what its tests showed and
  what is left. That answer is the turn's reply, so a delegated turn always reports to the turn that started it.
  The reply is headed by the harness's own line telling why the turn was closed (`synthetic.TURN_CLOSED`), so its
  reader knows the task may be unfinished. The calls of a closing answer are not run: a turn answering the closing
  prompt with calls, or malformed, ends refused as before, what it applied earlier still told.
- **The supervising turn decides.** The delegation skill tells a turn to review every report against what the
  harness shows, and one closed by a limit above all: it finishes the rest itself or delegates anew with a prompt
  corrected by what the report shows -- narrower, naming what is done and what remains -- never the same prompt again.

What came of the survey of November 2026 and is not built yet, in the order of its worth here:

1. **A report the harness verifies.** The report of a delegated turn headed by what the harness itself recorded --
   the files changed, the last outcome of every test binding run -- so the delegating turn reviews facts, not a
   subagent's account of them.
2. **A token or cost budget** of the settings beside the fuse: one round's context can be large, so rounds alone
   do not bound the spend.
3. **Steering.** A message of the delegating turn queued into a running subagent, as the user's own is, in place
   of stop and restart.
