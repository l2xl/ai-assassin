# Chat states

The server tells every state but *unread* — `state` stands beside every chat of `GET /api/chats`, and `asked` while it is
blocked; the held turns and services alerts that block a chat are the orchestrator's, designed and not yet raised, so a
chat is blocked today only where something sets its `asked`. A chat is in exactly one state, the first of this list that holds; the mark is the same wherever
the chat is named — the outline row, a hidden chat's `▾`, the indicator of a subagent in the chat
it was started from.

| state | mark | the chat |
|---|---|---|
| **blocked** | `⏸` amber | has a held turn — it waits for the user on an asked recommendation, a security alert or a services alert — or stands under a blocking alert of the model services without a turn |
| **working** | spinner | has a turn running — the model answering, a call applied, a scan running |
| **agents** | hollow spinner | ended its own turn while subagents it started still run in the background |
| **failed** | `⚠` red | ended its last turn on an error |
| **stopped** | `■` dim | had its last turn stopped |
| **unread** | `●` accent | holds a reply this tab has not shown |
| **waiting** | `○` dim | waits for the user's message |

- Blocked stands first because it is the one state only the user ends. A chat whose subagent is
  blocked is blocked itself, its mark leading to the chat that holds the request.
- The state is the server's, sent with the chat, so every page shows the same; only *unread* is
  the tab's own.
- Whether a chat is shown or hidden is not a state: a hidden chat carries the mark of its state
  on its `▾`.
- The mark's title names the state and, for blocked, what is asked (`blocked — recommends Raw command`).
