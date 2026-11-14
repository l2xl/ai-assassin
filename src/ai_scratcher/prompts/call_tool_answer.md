---
kind: skill
description: How the reply is written as text and the round closed with the answer tool
default: true
delivery: native
---
# Answer tool
Your answer reaches the harness through the answer tool of this session, `StructuredOutput`, which takes the `kind` and the `calls` and no text: the text of an answer is what you write as text ahead of the call. Call it once to close the round, with `kind: calls` and the calls to hand over tool calls or with `kind: text` to end the turn.
Write your reply once, as text, then call the tool with `kind: text`: the text written ahead of that call is your whole reply, so write nothing there but the reply, and a `kind: text` call with nothing written ahead of it is an empty answer, refused. The text written ahead of a `kind: calls` call or of another tool call is a short note of what you are about to do, shown in the log as said on the way.
