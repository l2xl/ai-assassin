# The bridge protocol

The bridge of a session connects to `ws://<host:port>/websurf` of its harness origin, with the token
its Assassin tab's URL carries. Every frame is one JSON object with a `type`:

| From | `type` | Fields | Meaning |
|---|---|---|---|
| extension | `hello` | `token`, `version` (3), `agent` (user agent) | the first frame after the socket opens |
| harness | `welcome` | — | the token is accepted; surf requests may follow |
| harness | `surf` | `id`, `action`, then `url` \| `tiling` \| `origin` \| `selector` \| `value` \| `steps` \| `max_chars` \| `max_edge` \| `max_pixels` as the action takes | one request |
| extension | `result` | `id`, `ok`, `page`, then the action's own fields — or `error` | the answer to the request of the same `id` |
| extension | `page` | `event` (`load` \| `history` \| `closed` \| `failed`), `page`, `error` (of `failed`) | a change of the surf tab |
| either | `ping` / `pong` | — | keepalive |

The harness accepts the upgrade only on a request addressing a loopback host (its `Host` header,
else `403`) and from a `chrome-extension://` or `moz-extension://` `Origin`, and
closes the socket (1008) unless its first message is a version 3 `hello` carrying the session token;
it then answers `welcome`. One extension is attached at a time: a newer one takes over and the older
is closed. Until `welcome` the extension answers a `surf` with an error and sends no `page` frame.
Either side answers a `ping` with a `pong`; the extension pings every 20 s, which keeps a Chrome
service worker from being stopped while idle, and the harness closes a bridge sending a message above
32 MiB. Neither side times a request or the connection out: a bridge lasts until its socket closes —
the browser gone closes it — and a request until its answer, its turn's stop or the bridge's end. The
extension reopens a dropped bridge from a 30 s alarm — which also wakes a background the browser has
stopped — replaces it at once for a newer token of its origin and closes it with its session.
