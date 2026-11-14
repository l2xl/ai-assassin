# File measuring

**The seed graph is never cut.** Every item of the selection enters with its
`@UID` line and its whole statement, in the selection's own order: the active item, its ancestors
and everything else the path brings. No item is shortened or left out, whatever the message — all
statements of this tree together are about 10k tokens.

What is measured is **the content of the files** the items name. A file either enters **whole**
or is measured **heavy** for this context, and then its items keep the **reference** alone: the
file's path, with its size in lines.

- **What to do with a heavy file is the AI's decision, not the Orchestrator's.** The model of the
  chat reads the task and the items and decides by itself: read the file in full, read a part of
  it, search it, or leave it. The Orchestrator prepares nothing in between — no outline, no
  summary, no excerpt.
- **The reference is enough because of the files tool**, which lists a
  folder and reads a file whole or by a range of lines, on every connection and in every mode.
- **A file is measured once.** A file named by several items is counted once, at the importance
  of the most important item naming it, and every item naming it lists it, whole or by reference.
- **Scores are ranks.** On this tree the cosine of a message to all items spans 0.25–0.64 around a
  median of 0.42, and the reranker's sigmoid stays under 0.25 for the right item: both order the
  items well and neither value means anything as a threshold. Nothing cuts by a raw score.
- **Estimation** orders the items, and through them their files:
  1. *Signals*, each a ranking of the items: dense similarity of the message to the statement
     embedded with its ancestors' subjects; lexical matches of file names and identifiers; the
     reranker over the dense shortlist; the chat's own activity (items it read, edited, named).
  2. *Fusion* by reciprocal rank, each signal under a weight of the settings (1 by default).
  3. *Propagation* over the DAG — personalised PageRank seeded with the fused scores, along
     parent and shared-source edges — so an item important by position rises without matching.
  4. *Pinned first.* The active item and every item whose UID the message names stand ahead of
     the propagated order, whatever their scores.
  5. *Budget*: the files are taken in the order of their items into the token budget; a file
     that fits what is left enters whole, one that does not is heavy and enters as its reference,
     and the files after it are still tried. The budget bounds the content of the files alone:
     the statements and the default prompt enter beside it. A token counts as four characters.
- **A large message is measured in segments.** A message is not a statement: a pasted test run or log
  reaches tens of thousands of characters — one of 26.8k measured 10.4k tokens, at 2.6 characters to
  a token, over the 8192 of the embedding model's window — and sent whole it is refused, the role
  marked failed and every chat blocked on an alert that a retry cannot clear, the same text being
  sent again. The dense and rerank signals therefore take the message in segments:
  1. *Cut along the structure.* Blank lines first, then lines, sentences and words, a fixed length
     only where no boundary is left; a segment is bounded in **characters** (2000), never in the
     estimated tokens, which that log shows to be off by half. A message that fits is one segment,
     unchanged.
  2. *Overlap by whole units.* A segment opens with the last whole units of the one before it, up to
     300 characters, so any run of whole units that long — an instruction among them — stands
     unsplit in at least one segment, wherever it falls.
  3. *The ends.* A message of more segments than a signal takes keeps its first and its last ones —
     the dense signal sixteen, the reranker six — where the ask stands; the middle of a paste is
     left out of the model signals alone.
  4. *The best segment.* An item scores the greatest cosine of any segment to it, and the greatest
     reranker score of any end segment: a long message ranks an item by its best-matching part, not
     by the average of everything pasted. Whether a mean of the best two would rank better is a
     question for a benchmark on the user's own messages; the maximum is the MaxP of document
     ranking, which was found to beat the first part and the sum.
  5. *One voice.* The segments of a signal become one ranking before the fusion, so a paste of forty
     segments weighs as one message, never forty signals. The lexical signal and the pinning read
     the whole message: the names in a pasted log count there at no model's cost.
- **Kept with the session.** The system prompt is composed when a session starts and stored with
  it: every round and every turn of the session sends the stored text, byte for byte, whatever
  changed on disk meanwhile. What changes later reaches the model at the tail, heading the next
  prompt as a **context update**, a step of that turn unfolding to its text: a heavy file a later message brought in whole, a statement edited, an item
  added, a file changed by someone other than this session (named, not resent — the files tool
  reads it). No file is taken back while the session lives; a new session estimates anew.
- **`for`.** A `context` call may name in `for` what the item is read for — the text its files
  are measured against; without it the turn's message stands in. The `syngate context` command
  stays unmeasured, every file whole: the CLI needs no model service.
- **Misses.** A heavy file the session then reads is noted in the server's memory with the message
  it was measured for. The notes feed the activity signal of later measurements during the same
  run of the server and are never written to disk: a new run estimates from scratch.
