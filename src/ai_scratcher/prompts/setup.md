---
kind: tool
description: Read the models a chat may run on and recommend one of them for the task at hand
calls:
  models: {}
  setup:
    required: [connection, model, reason]
    optional:
      effort: {type: string}
---
# Setup
`{"tool": "models"}` reads the models this chat may run on: one JSON line each, with its `connection` and `model`, its `family` and `tier` — a larger tier the stronger model of its family —, its `strengths` and its `efforts`, the model this chat runs on marked `"current": true`; what a connection does not state of a model is left out of its line.
`{"tool": "setup", "connection": "mixroute", "model": "claude-haiku-5-5", "effort": "low", "reason": "a rename needs no more"}` recommends one of the listed models for the task at hand, `effort` left out for the model's own; the harness answers with the recommendation as it stands.
- It recommends and changes nothing itself: the chat stays on its setup and your task goes on. A connection, a model or an effort the listing does not hold is refused, and so is a call without its reason.
