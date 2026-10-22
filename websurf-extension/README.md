# AI Assassin WebSurf extension

AI Assassin can already read the public web from its server. This browser extension covers what the
server cannot do: it hands the AI of each AI Assassin server you have open **one tab of your own
browser**, the *surf tab*, where pages load exactly as you would load them:

- **your sessions** — pages behind a login you already have in this browser, without the
  extension or the server ever holding your password or token;
- **your browser's identity** — a real navigation of a real browser, which sites that refuse bots
  accept;
- **your network and location** — your IP, region and local services.

In that tab the AI reads the live DOM — the page as its scripts have built it, with the current
state of its forms — and takes screenshots of it. With the chat's **Interactive WebSurf** switch on
(off by default) it also fills fields and uses the mouse: moves, clicks, double clicks, the wheel,
hover menus and drag and drop. Those events are synthetic; a page that insists on trusted input
ignores them, and the AI never types anywhere but through a fill.

Password, hidden, one-time-code and card fields and token `meta` elements are **redacted**: their
values are replaced by `[redacted]` in what the AI reads, covered by a black box in its
screenshots, and never filled by it — credentials are yours to type. Everything else the surf tab
shows **is sent to the model**: your logins stay in the browser, but the content behind them does
not. Install the extension only in a browser whose sessions you are willing to expose that way.

The extension does nothing by itself, and there is nothing to set up. It serves every AI Assassin
server whose page is open in this browser — the `http://127.0.0.1:<port>/?token=…` page `assassin`
opens — for as long as one of its tabs stays open: it reads that tab's URL, and nothing else of it,
connects to the server at `ws://127.0.0.1:<port>/websurf` with the token the URL carries and answers
the WebSurf requests the server sends at once, never waiting for a page to load; it reports what the surf tab
does — a page loaded, the one the AI opened included, a URL changed, the tab closed — so the AI
learns of it. A request acting on the page names the site it is meant for and is refused when the
tab has moved to another one meanwhile. Which sites may be reached is decided by the
server's guard, from the host lists in the `websurf` section of `assassin_settings.json` beside the
project's tree (see [`../BROWSER_EXTENSION.md`](../BROWSER_EXTENSION.md)); every request shows up as a
step in the chat.

## The surf tab

Each AI Assassin server open in the browser has a surf tab of its own; two servers never share or
touch each other's. Every page the AI opens loads in a fresh surf tab that replaces the previous one,
closed: no history, session storage or other state of one page's tab carries over to the next, while
your cookies and logins stay as they are. Everything else the AI does acts on that tab, and no other
tab is ever read, reported or touched. The first surf tab is placed next to its server's AI Assassin tab so you
can watch it: in the browser's split view where available (Chrome 155+), else in a new window tiled
against the AI Assassin window, else as the active tab of the current window when no AI Assassin tab
is open; each later one opens in its predecessor's place. In Firefox the surf window's title starts
with `WebSurf <port> · `, the port of the server whose AI drives it. On Linux under Wayland no browser
can position its windows: under KDE Plasma the AI Assassin server has KWin tile the two windows,
on another Wayland desktop the surf window opens where the desktop puts it; move it yourself.

The AI works only in a surf tab you can see. While it is out of sight — its window minimized,
another tab in front of it — every request is refused until you show it again. You or the AI may
close it at any moment; the next page the AI opens places a new one. When you close the last tab of
an AI Assassin server, its surf tab stays open as an ordinary tab the AI no longer drives.

The toolbar badge counts the AI Assassin servers connected and shows `●` while a request runs; the
toolbar button opens a page listing them, each with its connection and its surf tab.

## Install (developer mode)

The folder loads as is; there is no build step, and installing it is the whole setup. The browser
asks for access to all websites, to your tabs and to your browsing activity: the extension needs them
to find the AI Assassin tabs by their URL, to load, read and capture pages in the surf tab and to
follow its navigations.

### Chrome / Chromium (121 or later)

1. Open `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `websurf-extension` folder.
4. Pin *AI Assassin WebSurf* from the puzzle-piece menu if you want to see its badge.

After pulling changes, click the reload arrow on the extension's card.

### Firefox (121 or later)

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…** and choose `manifest.json` in this folder.
3. Open `about:addons` → *AI Assassin WebSurf* → **Permissions** and make sure access to all
   websites is on (or use the **Grant site access** button on the options page); without it the
   extension cannot read or capture the surf tab.

A temporary add-on is removed when Firefox restarts. To keep it, use Firefox Developer Edition or
Nightly with `xpinstall.signatures.required` set to `false` in `about:config`, zip this folder's
contents and install the zip from `about:addons` → gear → *Install Add-on From File…*.

## Use it

Start AI Assassin (`assassin`) and keep its page open in this browser — the
`http://127.0.0.1:<port>/?token=…` URL it prints and opens. That is all: the extension connects as
soon as the page is open, retries every 30 seconds when the connection drops, picks up the new token
when you open the page of a restarted server, and lets the server go when you close its last tab.

Only pages on `127.0.0.1`, `localhost` or `[::1]` at path `/` with a token are taken. A website that
sends a tab to such a URL makes the extension try that local port: an AI Assassin server there
accepts it only with its own token, but any other program listening on that port could drive a surf
tab, so close a tab you did not open and check the list behind the toolbar button.

## Files

| File | Role |
|---|---|
| `manifest.json` | one Manifest V3 file for both browsers |
| `background.js` | keeps the map of AI Assassin sessions, one bridge each, and routes requests and page events to each session's surf tab |
| `sessions.js` | tells an AI Assassin tab and its session from the tab's URL |
| `bridge.js` | the WebSocket protocol with an AI Assassin server |
| `surf.js` | serves a request on a session's surf tab: open, close, status, query, screenshot, fill, mouse |
| `page.js` | what runs inside the page: the DOM reader, redaction, fill, the mouse player, screenshot masks |
| `events.js` | the surf tabs' page events and the page info of their documents |
| `placement.js` | places a new surf tab next to its session's AI Assassin tab |
| `options.html`, `options.js` | the read-only list of sessions and the site-access grant |

The design and the protocol are in [`../BROWSER_EXTENSION.md`](../BROWSER_EXTENSION.md).
