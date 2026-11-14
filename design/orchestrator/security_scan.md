# Security scan

Text that came from outside the project may carry instructions. It is harmless while the session
only reads and answers; it matters the moment the session may act on it. The scan therefore
stands before the acts, not before the reading.

- **External text** is what is scanned: the result of a web fetch or search, the result of a
  WebSurf call of any action, and the report of a subagent whose session took any such text.
  Everything of the project is trusted — the tree, the project's files, the output of its tests,
  the AI's own edits — and so are the user's messages.
- **What alters.** A call that changes the tree, a project file (patch, replace), anything through
  the shell, the history (a recording git command), a page in the user's browser (WebSurf `fill`,
  `mouse`) — and a recommended permission, which widens what the next call may alter.
- **When it runs.**
  1. *Before the first altering call of a session*, over the external text the session holds by
     then; a session holding none passes without a call to any model.
  2. *Again only after external text came in.* Such a result marks the session; the next altering
     call is held until what came in since the last scan has been scanned, and the mark is
     cleared. A subagent started from a marked session starts marked.
  3. *Before a permission recommendation* is applied or asked, under the same two rules.

  A session calling its model again and again without any external result needs no further scan,
  however many altering calls it makes.
- **What it looks for** is prompt injection, and nothing else: text the session's model may take
  for an instruction addressed to it where no instruction belongs — a page, a search result, a
  report speaking to "the assistant" — and instructions that are strange for where they stand or
  lie outside the problem the session works on. What a page offers its human reader — a download,
  a script to run, a form to fill — is no finding: the browser guards that, not the scan. How
  injections are best detected is open research, and the scan agent's prompt is where it changes.
- **How.** The scan agent gets the text as fenced data and answers findings only: `{span,
  category, reason}`, the span being the exact wording found. Beside it one rule needs no model:
  invisible and bidirectional characters, which hide text from the reader. A span that is not in
  the text, or an answer that is not the schema, counts as a finding. Verdicts are kept in the
  server's memory by the hash of the scanned result, so none is scanned twice in one run.
- **Large text goes in windows.** External text beyond what the scan agent judges in one call
  (120,000 characters) is cut along the same units as a message — blank lines, lines, sentences,
  words — into windows overlapping by a quarter, so an instruction up to 30,000 characters long
  stands unsplit in at least one window. The agent judges each window, the findings of all are
  joined once each, and a span is still checked against the window it came from. The invisible
  characters need no window: the rule runs over the whole text. A payload split between distant
  windows, its parts harmless apart, is not guaranteed found — the scan is a tripwire — and a
  further pass over what the windows found is research the scan agent's prompt is not built for.
- **Holding a call.** The altering call waits while the scan runs. Without findings it is applied
  and the turn goes on unnoticed but for a step of the log.
- **A finding always pauses**: the turn is held on an alert (`⚠ 2 concerns in the context`)
  opening the **context review** — the external results the session holds, the findings
  highlighted with category and reason. A finding is settled by **dropping** its result from the
  session, a stub standing in for it, or by **accepting** it, which saves the finding's exact
  wording for the user: the same wording is no finding again, in any chat of any
  project. Once every finding is settled the held call is applied if all were
  accepted, and refused back to the model, with the reason, if anything was dropped.
- **A drop starts a new session.** The dropped result stands in an earlier message, so taking it
  out is the one cut that is not of the tail: the conversation goes on in a new session composed
  without it, and the turn continues there. The dropped text stays in the log, marked, and is not
  returned by the log tool.
- **A tripwire, not a guard.** A scan without findings reads `nothing found`, never `safe`: the
  permission switches and the tools' guards stay the limit. It does not stand before a read, so an
  instruction to fetch one more address is not stopped by it.
