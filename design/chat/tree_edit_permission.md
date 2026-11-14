# Tree edit permission

The Tree edit permission is the harness's own, on by default: while it is off a reply's add, edit,
move, rename and remove calls are refused (`tree edits are off for this chat — switch Tree edit
on`), the refusal going back to the model as its next prompt; query, context, skill, test and
agent stay allowed — reading the tree is the rail the harness runs on and is never switched off; a
delegated child cannot switch it on while its parent's is off, and one line ahead of the user's
text tells the model the tree is read-only for this chat, so it answers in text.
