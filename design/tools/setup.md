# Setup tool

The setup tool gives the AI two calls over the models a chat may run
on. It names no permission: a permission is recommended by the harness itself, when a call needs
one that is off.

- `{"tool": "models"}` — a read: every model a chat may run on, of every connection, with its
  connection, family, tier, strengths and efforts, the chat's own setup marked. A model
  configured without a description is listed without one.
- `{"tool": "setup", "connection": "…", "model": "…", "effort": "…", "reason": "…"}` — the
  recommendation of one of the listed models; `effort` may be left out.
