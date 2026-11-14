# Log tool

*Designed, not implemented.* The log tool reads the chat's full record, kept by the server
whatever was pruned from the session: `{"tool": "log", "turn": 7}` lists the turn's steps one line
each, `{"tool": "log", "turn": 7, "step": 3}` returns one in full, cut past a limit with the
offset to go on from. Text the user folded out, or a result a security finding dropped, is not
returned.
