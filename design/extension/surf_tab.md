# The surf tab

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

## Actions

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
refusal of a hidden surf tab, which carries none. The harness hands such an answer to the turn as the
refusal of its call: the browser's error, then, under *The surf tab shows:*, the page info fenced — the
page's origin alone where the host lists refuse it — so the turn reads where the tab stands; the
refusal ends its batch and comes back as the next prompt for the turn to look again and go on, the chat
step keeping the error alone.

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
boxes are painted, captures the visible tab (`tabs.captureVisibleTab`) and takes the boxes away. The
masks go into every frame in one injection; where the browser refuses that for any frame — Firefox
rejects the whole injection when one frame's answer cannot be returned, as for a frame that went away
under the script, which a page like Gmail churns all the time — they are laid frame by frame, each
failure its own: the top frame's failure is the screenshot's, and every other frame still there that
laid no masks is **covered** whole, a box over its frame element in the top frame (`cover`), the answer
counting them as `covered` and the harness telling the AI to read such frames with `query` instead. The
boxes are taken away the same way, frame by frame where one injection is refused, so none is left on
the page. The capture is scaled to the CSS pixels of the viewport, or below that to fit
the request's `max_edge` (longest side) and `max_pixels` (area), and encoded as a JPEG at quality 80:
the harness sets both to what the model sees unscaled, so a point of the image the model names maps
straight back to the viewport. The answer carries the image as a data URL, the viewport size in CSS
pixels, the device pixel `scale` of the top frame and the `image_scale`, image pixels per CSS pixel —
a point (x, y) of the image is (x / `image_scale`, y / `image_scale`) in the viewport. Chrome allows
two captures a second.
