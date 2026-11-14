# API connection session

The API is stateless, so the connection keeps the conversation itself, the way the `claude` CLI keeps
its sessions. A turn without a session opens one under a fresh id. The session's messages — each
user message and the answer to it, never the system prompt — are a JSON file
`<sessions dir>/<session>.json`, the sessions dir being `$XDG_STATE_HOME/ai-assassin/<connection id>`
(`~/.local/state/…` without the variable), outside the project like the CLI's transcripts; the
connection id `mixroute` keeps the sessions of the former MixRoute connector. A turn resuming a
session reads the file and sends its messages again. A session written only once the answer is in
leaves the file untouched by a failed or stopped request, so the retry of the same message starts
from the same history. A session id the folder does not hold — the folder cleared, or the chat
carried to another machine — fails the turn, asking for a new session; the page's `↺ New session`
then carries the kept messages as the transcript.
