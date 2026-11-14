# First setup

`assassin-setup` writes the settings a project starts with, so that the mandatory services are
there before the first message. The server runs it by itself when the settings hold no
`orchestrator` section, the chats showing `setting up the model services…` with the step at hand
until it ends; it is also run by hand.

1. **Hardware.** It asks for a card (`nvidia-smi`), takes the shipped model preset that fits its
   memory, serves it — `assassin-models up`, the first run
   downloading the image and the models — and merges the preset's model locators.
2. **Agents.** With the `claude` CLI installed it points the agents' model locators to the Claude Code
   connection: `haiku` for all of them, the scan included. Without it, they point to the
   first connection of the settings that offers a chat model, on that connection's first model;
   only a machine with no such connection is left with the agents' model locators unset. The scan reads bounded external text
   and answers a classification, which is the smaller model's work and has to be quick, since a
   call waits on it; `agents.scan` is the one line to change if it proves too weak.
3. **Model descriptions.** The models it knows — the Claude ones, those of the shipped presets —
   get their `family`, `tier` and `strengths`; the others are left to
   the user and are offered without them.
4. **Nothing is overwritten.** A key the settings already hold stays; the command reports what it
   wrote and which roles it could give no model locator — those are what the blocking alert then names.
