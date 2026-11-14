# AI connections

An AI connection carries a turn to a provider and its reply back. The seed context is the system
prompt of the turn and the user's text is the prompt; every `@UID` the text names brings that
item's statement in as one more section. Nothing else of the conversation travels except the
connection's own session, which the next replica resumes; a turn without a session (text was
folded out of or back into the exchange) carries the kept messages as a transcript heading the
text.

Every connection reports in its settings its models with their efforts and, where the configuration gives them, their family and tier — the line of models a model belongs to and its place within it — and their strengths — one line telling what the model is the right choice for — its call modes — each
listed with its label, hint, default and whether it is advanced, for the page's permission
switches — and its default setup: the model and effort a chat starts with, the effort one the
model lists or none. A chat of the page without a setup of its own starts with that model and
effort and the modes marked default.
