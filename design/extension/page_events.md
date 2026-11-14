# Page events

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
