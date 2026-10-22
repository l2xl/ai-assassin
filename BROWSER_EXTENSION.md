# Browser extension — the WebSurf tool

The extension in [`websurf-extension/`](websurf-extension/README.md) answers the harness's `websurf`
calls of every AI Assassin server open in the user's browser, each on a tab of its own. This
document is how it works — the sessions, the data flow, the protocol and the guards — and how to
install it in developer mode; installing it is the whole setup.

## How it works

```
          harness (src/ai_scratcher/websurf.py)          extension (websurf-extension/)
          ─────────────────────────────────────          ─────────────────────────────────────────────────
 request  AI turn ─websurf call─▶ guard ───── surf ────▶ bridge.js ▶ surf.js ─tabs, scripting─▶ surf tab
 answer   next prompt ◀─fenced── report ◀─── result ──── bridge.js ◀ surf.js ◀─ page info, DOM, image ─┘
 events   next prompt ◀─fenced── watch ◀──── page ────── bridge.js ◀ events.js ◀─ webNavigation, webRequest, tabs
```

The background (`background.js`) finds the Assassin servers open in the browser from the URLs of
their tabs and connects out to each over a WebSocket at `/websurf` on the server's own port — one
bridge per session, see *Sessions*. A `websurf` call that passes the guard goes out as a `surf` frame
on its server's bridge. The extension plays it on that session's surf tab —
navigation and capture through `tabs`, the DOM through `page.js`, injected by
`scripting.executeScript` into the extension's isolated world, where it sees the page's DOM but not
its scripts — and answers with the `result` frame of the same `id`. The harness checks the page the
answer landed on, fences it as untrusted and hands it to the turn as its next prompt, the request
showing as a chat step and every answer carrying websurf calls counting as one round of the turn.
What the surf tab does — the load an `open` started included — goes out as `page` frames and reaches
the turn with its next prompt.

**Nothing waits on the page.** The bridge carries requests and answers, never a page load: `open`
answers once the new tab exists and its navigation has started, `fill` and `mouse` once they have
played, and the loads, redirects and route changes that follow reach the AI as page events, which
it awaits with `wait` where it needs them. No side holds a request for a set time: the harness
awaits an answer until it comes, the browser detaches or the turn stops — a stopped turn stops
waiting while the page goes on — and a page action whose document goes away under it answers then.
`open` and `close` run one at a time, page actions as they come, so no page action, however stuck its
page, holds back the `open` or `close` that replaces or ends its tab.

**The origin travels with every page action.** The page may change under the AI at any moment — a
redirect, the page's own script, the user — so the harness keeps no page of its own to judge: every
`query`, `screenshot`, `fill` and `mouse` names the `origin` of the page it is meant for, the guard
judges that origin against the host lists, and the extension plays the action only in a top-level
document of that origin, refusing it otherwise with an error naming the document's own origin. The
AI then reads the page anew — `status`, or the page events — judges the change and repeats the call
with the new origin where it wants to act there.

Nothing is requested with `fetch()`: every page is a top-level navigation of the surf tab, and
everything the AI learns of it is read from the live, rendered document.

### Sessions

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

### The surf tab

Each session has one **surf tab**, the tab the extension drives for it. Every request of the session
but `open` acts on its surf tab open; while none is, they are refused with *no surf tab open*.
`close` closes it, as the user may at any moment; the next `open` creates a fresh one.

**A new tab for every load.** Each `open` loads its page in a new surf tab and closes the previous
one; it never navigates the tab it has. Every page the AI opens thus starts in a clean browsing
context, and nothing of one load's tab leaks into the next by accident — no back/forward history or
cached document to return to, no `sessionStorage`, no `window.name`, no state of the isolated world
(the mouse pointer, the screenshot masks). What the profile holds for every tab — cookies,
`localStorage`, IndexedDB, the HTTP cache — stays: those are the user's sessions the surf tab is
there to use.

The new tab takes the previous one's place: it opens in that tab's window at its index, active, and
only then is the previous one closed, the surf tab id moving to the new tab first, so the closing is
no `closed` page event. A tiled surf window thus survives the replacement instead of closing, the
Assassin window is not halved again on every `open`, and the chat window keeps the focus; the answer
names the previous tab's `placement` (`tab` where it is not known). A previous surf tab in a split
view is closed first, as the Assassin tab can join one split only, and its successor is placed anew.

A surf tab with no previous one's place to take — the first, or the successor of a split one — is
placed beside its session's Assassin tab, the first Assassin tab of the session's origin, by the
first placement that applies, named by `placement` in the answer:

1. `split` — where the browser has `tabs.createSplit` (tested at runtime, never by version), a new
   tab split with the Assassin tab, `tabs.create({url, splitWithTabId})`; split view is side by side;
2. `tiled` — otherwise, or when the split is refused, a new window beside the Assassin window, which
   is halved along its longer side (left/right when it is at least as wide as tall, else top/bottom):
   the Assassin window keeps the first half, the surf window takes the second — by the browser or by
   the compositor, as the harness's tiling method below sets; `window` where neither can;
3. `tab` — with no Assassin tab of the session open, the active tab of the previous surf tab's window
   when it replaces one, else of the current window; an inactive one would be hidden from the start.

**Tiling methods.** Wayland lets no client position its windows: the browser applies the size of
`windows.update` and `windows.create` but drops `left` and `top`, so a window the browser tiled would
halve the Assassin window where it stands and open where the compositor likes, on top of it. Only the
compositor places windows, and the harness, running in the user's session, can reach it. The harness
therefore reads its tiling method from the desktop once, as the server starts, and sends it with
every `open` as `tiling` — left out while it is `browser`, the extension's default:

- `browser` — X11 (`XDG_SESSION_TYPE=x11`), Windows, macOS, and a session telling no Wayland: the
  extension halves the Assassin window and opens the surf window over the second half itself.
- `kwin` — Wayland with `KDE` in `XDG_CURRENT_DESKTOP`, `qdbus6` (else `qdbus`) found and KWin's
  scripting (`org.kde.KWin /Scripting`) on the session bus: the extension opens the surf window and
  leaves the Assassin window as it is, and the `open` answer carries `tile`, `{surf, assassin}` — the
  surf window's label and the Assassin tab's title, its window's caption while it is the active tab
  there (the Assassin page is titled `<item> · AI Assassin`), else `null` — for the harness to tile
  both windows. The placement is `tiled`.
- `none` — any other Wayland desktop: the surf window opens where the desktop puts it, the Assassin
  window left as it is; the placement is `window`.

A replacement surf tab reuses its window, so a window is tiled once, when it is created.

**The window label.** Every surf window the extension creates is labelled `WebSurf <port> · ` in
front of its title — the port of its session's harness origin — through Firefox's
`windows.create({titlePreface})`, so the user sees which window the AI drives for which server, and
KWin finds it by its caption. Chrome has no `titlePreface` and refuses a property it does not know, so
the label goes only to a browser that has `runtime.getBrowserInfo`, Firefox; a Chrome surf window is
unlabelled (Chrome mostly takes the split placement anyway).

**Compositor tiling** (`src/ai_scratcher/tiling.py`). On an `open` answer carrying `tile` under `kwin`,
the harness, off the turn's thread, unloads the session's previous KWin script, writes the new one to
a temporary file and loads and runs it over D-Bus — `qdbus6 org.kde.KWin /Scripting
org.kde.kwin.Scripting.loadScript <file> ai-assassin-websurf-<port>`, then `org.kde.kwin.Script.run`
on `/Scripting/Script<id>`, after which the file goes. The KWin 6 script finds the surf window by its
caption prefix — waiting for it through `workspace.windowAdded` and the window's `captionChanged` where
it is not mapped or labelled yet — and the Assassin window, a normal window that is not the surf
window, by its caption; it takes the work area of the Assassin window's screen
(`workspace.clientArea(KWin.MaximizeArea, window)`), un-maximizes both, and gives the Assassin window
the first half and the surf window the second along the longer side. Without an Assassin window found
it gives the surf window the second half of its own screen alone. A tiling that fails never fails the
websurf call: it is told on the server's stderr at most.

The limits: the Assassin window is found by its title, so with the Assassin tab not the active one of
its window only the surf window is placed; an unlabelled Chrome window is not tiled at all; and `none`
leaves the placement to the desktop.

**Out of sight, out of service.** While the surf tab is hidden from the user, every request —
`open` included — is refused with an error naming why and no page info, until the user shows it
again; once the user closes it, the next `open` creates a fresh one. The surf tab is hidden when its
window is minimized, when the browser hides the tab (Firefox's `tab.hidden`), when it is not the
active tab of its window and shares no split view (`splitViewId` other than -1), or when its page
reports `document.visibilityState` other than `visible`, which also covers an occluded window and a
split view behind another tab. The tab's own state decides `open`, `close` and `status`; a page
action asks the page too, in the very script that plays it, so no separate question to a page that
may never answer holds the request.

### Actions

| `action` | Fields | Kind | Answer |
|---|---|---|---|
| `open` | `url`, `tiling` (but `browser`) | passive | the page info of the navigation started, `placement`, `tile` (a new window under `kwin`) |
| `close` | — | passive | `ok` once the surf tab is closed |
| `status` | — | passive | the page info as it is now |
| `query` | `origin`, `selector` (optional), `max_chars` (optional) | passive | the page info, `dom`, `matches`, `truncated` |
| `screenshot` | `origin`, `max_edge`, `max_pixels` | passive | the page info, `image`, `viewport`, `scale`, `image_scale` |
| `fill` | `origin`, `selector`, `value` | interactive | the page info once played |
| `mouse` | `origin`, `steps` | interactive | the page info once played |
| `wait` | `seconds` (optional) | passive, the harness's own | the number of page events it saw |

The **page info** is `{url, title, status, content_type}`: the final URL after redirects, the tab's
title, the HTTP status and `Content-Type` of the main document — `null` where the browser reported
none, as for a document restored from the back/forward cache or one still loading. A failed request
answers `ok: false` with its `error` and, where the tab is still there, the page info — but for the
refusal of a hidden surf tab, which carries none.

The **page actions** — `query`, `screenshot`, `fill` and `mouse` — carry the `origin`
(`scheme://host[:port]`, as `URL.origin` serializes it) of the page they are meant for. Each plays
only where the surf tab's top-level document has that origin, checked in the script that plays it;
any other document — another origin, an opaque one (`about:blank`) — refuses it with *the surf tab's
page is on …, not …*, the page info attached. A page action whose document goes away while it plays
— a new document committed in the surf tab (`webNavigation.onCommitted`, frame 0) or the tab closed —
answers then with an error saying so.

**`open`** loads its URL in a new surf tab, as above, and answers as soon as the tab exists and its
navigation has started, with the page info of the pending document — the URL asked for, its status
and content type not yet known. The load, its redirects and its failure reach the harness as page
events. Only `http` and `https` URLs are opened, always as a GET.

**`close`** closes the surf tab; its closing reaches the harness as the `closed` page event.

**`query`** serializes the live DOM of the top frame — the document as scripts have built it:
elements with their tags and attributes, text, and the current state of form controls as attributes
(`value`, `checked`, `selected`, a `textarea`'s value as its text). `script`, `style`, `noscript` and
`template` contents, the inside of `svg` and comments are dropped and whitespace is collapsed; an
open shadow root is serialized as a `<template shadowrootmode="open">` of its host, frames and closed
shadow roots appear only as their host elements. With a CSS `selector` it answers each match in
document order and their count, without one the whole document; an invalid selector is an error. The
text is cut to `max_chars`, 200 000 by default and at most.

**`fill`** acts on the first element the selector matches as typing into it would: it focuses it,
sets its value through the native `value` setter of the element's prototype — past a framework's own
`value` property, so React and the like see the change — or the text of a `contenteditable` element,
then dispatches bubbling `input` and `change` events. It takes a text-like `input`, a `textarea`, a
`select` (the option of that value, else of that label) and a `contenteditable` element; any other, a
disabled or read-only one and every sensitive element are refused.

**`mouse`** plays up to 100 `steps` as the user's pointer would, from where the previous request left
it — the centre of the viewport after a load. A step's target is `x`, `y` in viewport CSS pixels (a
screenshot's image coordinates divided by its `scale`) or a `selector`, the centre of its first
match, scrolled into view first when outside; a pressing step may name the `button`, `left` (the
default), `middle` or `right`.

| Step `type` | Fields | Effect |
|---|---|---|
| `move` | target, `count` | a straight path of `count` points (10 by default, 100 at most), each a `pointermove` and `mousemove` with the buttons held — a stroke while one is down |
| `down` | target (optional), `button` | moves to the target if given, then `pointerdown`, `mousedown`; a left press focuses the focusable element it hits (or blurs), a right one also fires `contextmenu` |
| `up` | target (optional), `button` | moves to the target if given, then `pointerup`, `mouseup`, and `click` (left) or `auxclick` (middle) where the press and the release hit the same element |
| `click` | target, `button` | `move`, `down`, `up` |
| `dblclick` | target | two left clicks of `detail` 1 and 2, then `dblclick` |
| `wheel` | target (optional), `dx`, `dy` | a `wheel` event at the pointer, then, unless cancelled, scrolls the nearest scrollable ancestor or the window |
| `pause` | `ms` | waits, 2000 ms at most and 10 s over the request — a long press is `down`, `pause`, `up` |

Every event goes to the element under the pointer (`elementFromPoint`, inside open shadow roots) with
the pointer's coordinates and buttons; where that element changes, the `pointerout`/`mouseout` and
`pointerleave`/`mouseleave` of the old one and the `pointerover`/`mouseover` and
`pointerenter`/`mouseenter` of the new one fire first, so hover menus and tooltips react. A cancelled
`pointerdown` keeps the mouse events of its press from firing, as in the browser.

**Drag and drop.** A `move` with the left button down that starts on a `draggable` element or inside
one begins an HTML5 drag — `dragstart` with one shared `DataTransfer`, then `drag`, `dragenter`,
`dragover` and `dragleave` along the path in place of the mouse moves, and at the `up` a `drop` where
the last `dragover` was cancelled (else `dragleave`) and `dragend`. A cancelled `dragstart` leaves the
moves plain. Libraries built on pointer or mouse events — sortable lists, sliders, canvases — get
those events themselves.

The events are synthetic (`isTrusted` false) and carry no user activation and no modifier keys: a
page that insists on trusted input ignores them, a click that opens a popup is blocked by the
browser, and a `select` does not drop down — it is set with `fill`. They play in the top frame; an
iframe gets them on its own element only. There is no keyboard input beyond `fill`.

**No settling.** A `fill` or `mouse` answers once it has played, with the page info as it then is; a
navigation or route change it started reaches the AI as page events, awaited with `wait`.

**`screenshot`** activates the surf tab in its window — which matters only for the inactive pane of
a split view, the one surf tab in sight that is not the active tab — lays an opaque box over every
visible sensitive element in every frame, without awaiting a frame there — a frame scrolled out of
sight never renders one —, has the visible top frame await two animation frames (`paint`) so the
boxes are painted, captures the visible tab (`tabs.captureVisibleTab`) and takes the boxes away. The capture is scaled to the CSS pixels of the viewport, or below that to fit
the request's `max_edge` (longest side) and `max_pixels` (area), and encoded as a JPEG at quality 80:
the harness sets both to what the model sees unscaled, so a point of the image the model names maps
straight back to the viewport. The answer carries the image as a data URL, the viewport size in CSS
pixels, the device pixel `scale` of the top frame and the `image_scale`, image pixels per CSS pixel —
a point (x, y) of the image is (x / `image_scale`, y / `image_scale`) in the viewport. Chrome allows
two captures a second.

### Page events

| `event` | Browser signal, frame 0 of the surf tab only | Means |
|---|---|---|
| `load` | `webNavigation.onCompleted` | a new document has loaded with all its resources |
| `history` | `webNavigation.onHistoryStateUpdated`, `onReferenceFragmentUpdated` | the URL changed within the document (`pushState`, `replaceState`, `#fragment`) |
| `closed` | `tabs.onRemoved` | the surf tab is gone; the frame carries its last known page |
| `failed` | `webNavigation.onErrorOccurred` | a navigation failed — the frame carries the browser's `error` (`net::ERR_NAME_NOT_RESOLVED`) and the URL it went to, no response joined |

`webNavigation.onCompleted` fires once per top-level document, after its `load`, whoever started the
navigation — the AI, the page's script or the user. No navigation event carries the HTTP status, so
the extension keeps the surf tab's last main-frame response from `webRequest.onCompleted`
(`types: ['main_frame']`, with `responseHeaders`) and joins its status and `Content-Type` into the
page info of the document it loaded.

The harness keeps the last 50 events. A turn that has surfed gets with each next prompt every event
recorded since its previous prompt, those its own requests caused included: the answer of a request
tells the page as it was when it answered, the events what came of it.

**`wait`** is the harness's own action and never reaches the browser: it answers once a page event
newer than the turn's last websurf call and than its previous prompt has been recorded — at once
when one already has — with the number of events it saw, the events themselves coming with the next
prompt. Without `seconds` it waits as long as it takes; the turn's stop, the browser detaching, or
the `seconds` the AI gives end it sooner. Within one answer `[open, wait, query]` opens a page,
awaits its first event and reads it in a single round.

### The surf tab hold

All chats of a server share its one surf tab. Any turn may read and act on the page it shows — the origin each
page action carries refuses it on a page that changed under it — so turns and their subagents can
work on one page together. Replacing or ending the page is held: the turn whose `open` loaded the
surf tab's page holds the tab while it runs, and an `open` or `close` of any other turn — but the
turns it delegated, directly or not — is refused, naming the holding turn. The hold lapses as the
turn ends, so it is soft: it orders the turns' new pages, it never locks the user or the page out.

### The bridge protocol

The bridge of a session connects to `ws://<host:port>/websurf` of its harness origin, with the token
its Assassin tab's URL carries. Every frame is one JSON object with a `type`:

| From | `type` | Fields | Meaning |
|---|---|---|---|
| extension | `hello` | `token`, `version` (3), `agent` (user agent) | the first frame after the socket opens |
| harness | `welcome` | — | the token is accepted; surf requests may follow |
| harness | `surf` | `id`, `action`, then `url` \| `tiling` \| `origin` \| `selector` \| `value` \| `steps` \| `max_chars` \| `max_edge` \| `max_pixels` as the action takes | one request |
| extension | `result` | `id`, `ok`, `page`, then the action's fields of the table above — or `error` | the answer to the request of the same `id` |
| extension | `page` | `event` (`load` \| `history` \| `closed` \| `failed`), `page`, `error` (of `failed`) | a change of the surf tab |
| either | `ping` / `pong` | — | keepalive |

The harness accepts the upgrade only from a `chrome-extension://` or `moz-extension://` `Origin` and
closes the socket (1008) unless its first message is a version 3 `hello` carrying the session token;
it then answers `welcome`. One extension is attached at a time: a newer one takes over and the older
is closed. Until `welcome` the extension answers a `surf` with an error and sends no `page` frame.
Either side answers a `ping` with a `pong`; the extension pings every 20 s, which keeps a Chrome
service worker from being stopped while idle, and the harness closes a bridge sending a message above
32 MiB. Neither side times a request or the connection out: a bridge lasts until its socket closes —
the browser gone closes it — and a request until its answer, its turn's stop or the bridge's end. The
extension reopens a dropped bridge from a 30 s alarm — which also wakes a background the browser has
stopped — replaces it at once for a newer token of its origin and closes it with its session.

## Guards

### In the extension

- **Loopback sessions only.** A session is taken only from a tab at `http://` on `127.0.0.1`,
  `localhost` or `[::1]`, path `/`, with a token, and of that tab only the URL is read.
- **One tab per session.** A session's requests act on its surf tab alone, and its page events are
  those of that tab's top frame alone, sent on its own bridge; no other tab is ever read, reported or
  touched, and a released surf tab no longer is.
- **The named origin.** A page action plays only in a top-level document of the origin it names,
  checked in the script that plays it.
- **A clean tab per load.** Every `open` loads in a new tab and closes the previous one, so no
  history, session storage or isolated-world state carries from one load to the next.
- **In the user's sight.** No request is played on a surf tab the user cannot see.
- **http and https only.** `open` refuses any other scheme.
- **Sensitive elements.** An `input` of `type` `password` or `hidden`; an `input` or `textarea` whose
  `autocomplete` names `current-password`, `new-password`, `one-time-code`, `cc-number`, `cc-csc`,
  `cc-exp`, `cc-exp-month` or `cc-exp-year`; a `meta` whose `name` contains `csrf` or `token`. A
  `query` replaces their value — the attribute and the live value — with `[redacted]`, keeping the
  element; a `screenshot` masks the visible ones with opaque boxes in the top layer, above dialogs,
  inside shadow roots too; a `fill` refuses them.
- **Isolated world.** `page.js` runs in the extension's isolated world: the page's scripts can
  neither see nor call it.
- **Authenticated first.** No request is played and no page event sent before the harness's
  `welcome`.
- **Never held by a page.** No request awaits a load or a set time; a page action answers when its
  document goes away, and none holds back an `open` or `close`.
- **Bounded input.** A mouse request holds at most 100 steps, a move 100 points, a pause 2 s and the
  pauses of a request 10 s; a DOM is cut to 200 000 characters; a screenshot fits the harness's size.

### In the harness

- **Every call checked.** The action is known, its fields well typed, `max_chars` a positive integer
  capped at 200 000, a mouse request 1 to 100 steps of known types and buttons, a page action's
  `origin` an http or https origin (a URL counts by its origin). A refused call never reaches the
  browser.
- **Host lists.** The origin a call names — an `open` URL's, a page action's `origin` — carries no
  credentials and is one the host lists admit: a blocked origin never; with an allowlist only a
  listed one; a private, loopback or link-local host (127.0.0.0/8, ::1, 10/8, 172.16/12,
  192.168/16, 169.254/16 with the cloud metadata address) only by an exact allow entry. The harness
  keeps no page of its own to judge: what the tab shows when the action plays is the extension's to
  check against the named origin.
- **The landed page counts.** An answer whose page is on an origin the lists refuse is withheld but
  for its origin, and a page event from one is told by its origin alone — the URL past the origin is
  the page's to write. A page that is not http or https (`about:blank`, a browser error page) counts
  as refused.
- **Interactive by permission.** `open`, `close`, `status`, `query`, `screenshot` and `wait` are
  always on; `fill` and `mouse` need the chat's Interactive WebSurf switch
  (@AI_CHAT-PERMISSION-WEBSURF), off by default and offered while a browser is attached.
- **Held new pages.** An `open` or `close` is refused while another running turn — not one the
  caller descends from — holds the surf tab (see *The surf tab hold*).
- **Fenced.** The page info, the DOM and the page events reach the AI between two lines of a random
  `untrusted-…` marker, under a notice that they are data, never instructions; a screenshot is
  attached as an image.
- **Visible.** Every request is a chat step showing its action, its target and the size of its
  answer; an answer is awaited until it comes, the browser detaches or the turn stops.

The host lists are the `websurf` section of the server settings file `assassin_settings.json`
(@ASSASSIN-SETTINGS), read at every use:
`{"websurf": {"allow": ["https://example.com", "https://*.example.org", "http://192.168.1.10:8080"], "block": ["https://*.bank.example"]}}`.
An entry is an exact origin (the default port may be left out), `scheme://*.domain[:port]` for a
domain and its subdomains, or `*` for any origin; a wildcard never admits an internal host. `block`
wins over `allow`; an empty or missing `allow` admits every public origin, so with no settings WebSurf
reaches the public web and nothing internal. Hosts are judged as written, the numeric IPv4 forms a
browser accepts (`127.1`, `2130706433`) included; names are not resolved.

## Install in developer mode

The folder loads as is, with no build step. One Manifest V3 serves both browsers: Chrome runs
`background.service_worker` as a module service worker, Firefox runs `background.scripts` as a module
event page under the id `websurf@ai-assassin`, each ignoring the other key; the code takes
`globalThis.browser ?? globalThis.chrome`, and the extension-page policy
`script-src 'self'; object-src 'self'` keeps Firefox from upgrading the loopback `ws://`. The browser
asks for access to all websites (`<all_urls>`) and for `tabs`, `scripting`, `webNavigation`,
`webRequest`, `storage` and `alarms`.

### Chrome / Chromium 121 or later

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose the `websurf-extension` folder.
3. Pin *AI Assassin WebSurf* from the puzzle-piece menu to see its badge.

After pulling changes, click the reload arrow on the extension's card. Split-view placement needs a
Chrome with `tabs.createSplit` (155 or later); older ones tile windows.

### Firefox 121 or later

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…** and choose `websurf-extension/manifest.json`.
3. In `about:addons` → *AI Assassin WebSurf* → **Permissions**, turn on access to all websites, or
   click **Grant site access** on the extension's options page; without it the surf tab can be
   neither read nor captured.

After pulling changes, click **Reload** on the extension in `about:debugging`. A temporary add-on is
gone when Firefox restarts. To keep it, use Developer Edition or Nightly with
`xpinstall.signatures.required` set to `false` in `about:config`, zip the folder's contents and
install the zip from `about:addons` → gear → *Install Add-on From File…*; Release and Beta install
only an XPI signed by Mozilla (an unlisted AMO submission).

### Use it

There is nothing to connect: start `assassin` and open the URL it prints,
`http://127.0.0.1:<port>/?token=…`, in the browser — the page `assassin` opens itself counts — and
the extension serves that server while one of its tabs stays open. Several servers open at once are
served side by side.

The toolbar button opens the options page, a read-only list of the sessions — each server's origin,
its bridge (`connecting`, `authenticating`, `connected`, `disconnected`) and its surf tab, if any —
with the **Grant site access** button. The badge counts the sessions connected and shows `●` while a
request runs. Host lists, where wanted, go into `assassin_settings.json` as above; an edit takes
effect without a restart.
