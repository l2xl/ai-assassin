# Surf tab hold

All chats of a server share its one surf tab. Any turn may read and act on the page it shows — the origin each
page action carries refuses it on a page that changed under it — so turns and their subagents can
work on one page together. Replacing or ending the page is held: the last turn whose `open` or
`close` passed holds the surf tab while it runs, and an `open` or `close` of any other turn — but the
turns it delegated, directly or not — is refused, naming the holding turn; a call of no turn takes no
hold. The hold lapses as the
turn ends, so it is soft: it orders the turns' new pages, it never locks the user or the page out.
