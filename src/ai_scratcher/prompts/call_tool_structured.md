---
kind: skill
description: How the structured answer closes a round through the answer tool, the reply written as text ahead of it
default: true
delivery: native
---
# Structured answer
Your answer reaches the harness through the answer tool of this session, `StructuredOutput`, which takes the `kind` and the `calls` and no text: the text of an answer is what you write as text ahead of the call. Call it once to close the round, with `kind: calls` and the calls to hand over tool calls or with `kind: text` to end the turn.
Write your reply once, as text, then call the tool with `kind: text`: the text written ahead of that call is your whole reply, so write nothing there but the reply, and a `kind: text` call with nothing written ahead of it is an empty answer, refused. The text written ahead of a `kind: calls` call or of another tool call is a short note of what you are about to do, shown in the log as said on the way.
Text and tool belong to one response. Where a response of yours ended on text without the tool and you are asked to call it, call it at once and write nothing more: the text you already wrote stands ahead of the call and is the reply, and whatever you write again is added to it, said and paid twice. Once the tool has answered, write nothing: the round is closed.
A workflow you launch is awaited: the turn lasts until it has reported and you have answered again, and only that last answer counts. A shell command left running in the background is killed when the turn ends, so await it instead.
