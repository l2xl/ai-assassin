# Statement changes

**Statement changes.** A conversation remembers the anchored statement as its previous turn
carried it (`statement`, stored with the conversation). When a turn starts and the statement
differs — changed in the page, on disk or by the AI's own `edit` — the turn is headed by a user
message of the log (`statement: true`, shown under `statement changed`): `The statement of @UID
now reads:` and the statement, so the AI learns of the change at its next turn, whatever the
session. The editor's send into a shown conversation is that message alone. The seed context of
every turn already carries the current statement; the message is what tells the model it moved.
