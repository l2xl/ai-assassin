# Sessions

Nothing is typed and nothing is injected for the setup: the extension finds the servers to serve in
the browser's own tab strip, reading nothing of any page but its URL. An **Assassin tab** is a tab
whose URL is `http://<host>:<port>/?token=<t>` — the host a loopback literal, `127.0.0.1`,
`localhost` or `[::1]`, the path `/`, the `token` query parameter not empty — the URL `assassin`
prints; the page reads its token from `location.search` and never strips it, so the URL carries it
for the page's whole life. A surf tab never counts as one, whatever page the AI opens in it.

Every harness origin with an Assassin tab is a **session**. The background finds them with
`tabs.query` when it starts and follows `tabs.onUpdated` (URL changes) and `tabs.onRemoved`, and keeps
their map itself: harness origin → its token, its Assassin tabs with the token each carries, its
bridge socket and its surf tab (`tabId`, `placement`, the last response and page info). The tab ids,
tokens and placements are kept across a restart of the background in `storage.session` — in memory,
gone with the browser — or in `storage.local` where the browser has no session storage; the sockets
are reopened then, and a tab the restart left out is found again by the scan.

- A session's bridge opens when the first Assassin tab of its origin appears, its `hello` of
  protocol version 3 carrying the token read from the URL. Several tabs of one server are one session
  and one bridge.
- A newer token for the origin — the server restarted and its page reopened — replaces the bridge:
  the token of the Assassin tab seen last is the session's.
- A dropped bridge — an engine restart keeps the port and the token — is reopened by the 30 s alarm.
- When the last Assassin tab of its origin closes or leaves that URL, the bridge closes and the
  session ends; its surf tab is **released**, left open as an ordinary tab that is no longer driven
  nor reported.

A server is thus served only while one of its pages is open in a browser with the extension;
without one, the harness refuses a websurf call with *no browser attached*, telling the AI to have
the page opened there.

**Isolation.** The requests of a session's bridge act on that session's surf tab alone, a new surf
tab is placed beside that session's own Assassin tab, and the page events of a surf tab go to the
bridge of the session owning it alone. Two Assassin servers open in one browser thus run two bridges
and two surf tabs that never cross.

**What discovery trusts.** Only loopback literal hosts at path `/` with a token are taken, and
nothing of a page is read but its URL — no content script, no meta tag, no change to the Assassin
page. A web page that navigates a tab to a loopback URL with a token makes the extension try that
port with that token. An Assassin server holding another token closes the bridge at once, and only
one holding that very token welcomes it; but a hostile program already serving on that port welcomes
whatever it is sent, and can then drive a surf tab with the user's sessions — under the extension's
guards, not under any server's host lists — for as long as that tab stays open. Such a program
already runs on the user's machine; the options page and the badge show every session served, and
closing the tab ends it.
