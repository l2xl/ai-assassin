# Setup selector

The setup pill (`.chat-setup`, titled `connector · model · effort — click to change`; with a single
connector it reads `model · effort ▾`, the connector named in its title) opens the menu choosing the connector, its model and the
efforts that model supports, in steps within one opening: a connector click rebuilds the model list in
place, a model click shows that model's efforts, and only an effort click — or the click of a model
offering no effort — chooses the whole setup and closes the menu, so a change of connector, model
and effort is three clicks. The menu also holds the three resets: `↺ New session` keeps the shown history and
drops the connector session, so the next turn starts a new one headed by the kept messages;
`＋ New chat` (`begin`) files the live conversation behind `▾` and leaves an empty one, unasked;
`✕ Delete chat` (`erase`) erases the live conversation's log and session after confirmation
(`Delete this chat of UID? Its N messages and session are erased.`), the filed ones untouched. All
three are refused while a turn runs.
