---
kind: skill
description: The round of a turn — a reply ends it, calls go on with their results as the next prompt
default: true
---
# Tool calls
A turn runs in rounds, one answer each: a text answer is your reply and ends the turn; a calls answer hands the harness tool calls, with text said beside them where you have any, and the turn goes on with the next round. How an answer is carried is told by the skill of your connection.
Every call is an object whose `tool` names one of the tools defined to you, its other keys being the fields of that tool. The calls are applied in order and the first refused one stops the batch: the refusal comes back to you as the next prompt, with the results of the calls applied before it, for you to correct the call or answer in text.
What a call read or ran is not your answer but your next prompt: the harness places the results of the batch into the same session as the next message and the exchange goes on with your next answer, for a bounded number of rounds.
