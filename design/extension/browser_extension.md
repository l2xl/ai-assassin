# Browser extension — the WebSurf tool

The extension in [`websurf-extension/`](websurf-extension/README.md) answers the harness's `websurf`
calls of every AI Assassin server open in the user's browser, each on a tab of its own, where pages
load as the user would load them — with their sessions, network identity and location — for the AI
to read, see and, where permitted, operate. This
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
bridge per session. A `websurf` call that passes the guard goes out as a `surf` frame
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

## Guards in the extension

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
  inside shadow roots too, and covers whole a frame it could not mask; a `fill` refuses them.
- **Isolated world.** `page.js` runs in the extension's isolated world: the page's scripts can
  neither see nor call it.
- **Authenticated first.** No request is played and no page event sent before the harness's
  `welcome`.
- **Never held by a page.** No request awaits a load or a set time; a page action answers when its
  document goes away, and none holds back an `open` or `close`.
- **Bounded input.** A mouse request holds at most 100 steps, a move 100 points, a pause 2 s and the
  pauses of a request 10 s; a DOM is cut to 200 000 characters; a screenshot fits the harness's size.

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
its bridge (`connecting`, `authenticating`, `connected`, `disconnected`) and its surf tab, if any,
never its token —
with the **Grant site access** button. The badge counts the sessions connected and shows `●` while a
request runs. Host lists, where wanted, go into `assassin_settings.json`; an edit takes
effect without a restart.
