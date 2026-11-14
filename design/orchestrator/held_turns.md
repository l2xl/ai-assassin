# Held turns

A turn waiting for the user — on an asked recommendation, a security alert or a services alert —
is **held**. A held turn is still the chat's turn: stop ends it, a typed message
queues behind it, `send!` stops it and sends, and a reset or a rename is refused as for a running
one. It has no timeout and, like a running turn, does not survive a restart of the server: it
ends as stopped. A delegated turn is held as any other: its recommendation and its security
alert stand in its own chat and show as **blocked** on its indicator in the chat it
was started from, whose turn goes on waiting for it.
