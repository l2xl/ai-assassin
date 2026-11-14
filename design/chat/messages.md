# Message styles

**Styles.** A message is a full-width row of the log (`.chat-msg`) whose body (`.msg-body`) is
the bubble: the user's (`.chat-msg.user`) styled as the description text, flush left on the panel
background, shown as typed, not rendered; the AI's reply (`.chat-msg.ai`) shifted right and
highlighted — the roles switch one body style, nothing more. A reply a delegated turn produced is
headed `delegated by UID (turn n)` (`.msg-from`).

**Collapsible sections**. A reply renders a `<details>` block — its
`<summary>…</summary>` on the same line or the next, markdown up to the matching `</details>`
line — as a section folded to its summary (`details.md-fold`, `▸` dim), expanded on a click;
`<details open>` starts expanded. The reader's choice survives the re-renders of the log. The
answer format skill asks the AI to write its long or secondary lists so,
the point of the answer staying in sight. The tags are not text: the selection steps over them.
