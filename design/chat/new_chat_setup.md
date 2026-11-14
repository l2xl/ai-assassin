# New chat setup

**New chats.** The connector, model, effort and the main permission switches chosen while the shown
conversation is a new one — the live chat holds no message, or this tab's view stands for a new
conversation — are kept in the `chat` section of `assassin_settings.json` and are the setup of every
next new chat: every new conversation shows it at once — an empty chat already open in another block,
and the new conversation an item with history begins when its chat is opened again — only the advanced
permissions switched on in a chat staying its own; the page applies the choice locally and keeps it over
a tree read until the server has stored it. A chat holding messages keeps its own setup in the chats store and a change there never reaches
the settings.
