# WebSurf guard of the harness

- **Every call checked.** The action is known, its fields well typed, `max_chars` a positive integer
  capped at 200 000, a mouse request 1 to 100 steps of known types and buttons, a page action's
  `origin` an http or https origin (a URL counts by its origin). A refused call never reaches the
  browser.
- **Host lists.** The origin a call names — an `open` URL's, a page action's `origin` — carries no
  credentials and is one the host lists admit: a blocked origin never; with an allowlist only a
  listed one; a private or link-local host (10/8, 172.16/12, 192.168/16,
  169.254/16 with the cloud metadata address) only by an exact allow entry. A loopback host
  (`localhost`, `*.localhost`, 127.0.0.0/8, ::1) is the user's own machine, where a web project
  under test is served by hand: it passes like a public origin, with no entry needed. The harness
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
  caller descends from — holds the surf tab.
- **Fenced.** The page info, the DOM and the page events reach the AI between two lines of a random
  `untrusted-…` marker, under a notice that they are data, never instructions; a screenshot is
  attached as an image.
- **Visible.** Every request is a chat step showing its action, its target and the size of its
  answer; an answer is awaited until it comes, the browser detaches or the turn stops.
- **Bounded rounds.** Every answer carrying websurf calls is one round of the turn. A turn that has
  surfed — got a browser's answer or waited for a page event — runs up to `websurf.rounds` of the
  server settings, 40 without one (`websurf.ROUNDS`), in place of the round fuse
  (`orchestrator.rounds`, `synthetic.QUERY_ROUNDS` without one); the results prompt names the rounds
  left once three or fewer remain, and a turn at the bound is asked for its closing report, ending
  refused when it answers that with calls. The tool's text tells the AI to batch what
  belongs together into one answer.
- **Recovery told.** The tool's text tells the AI that a refusal ends its batch alone — the calls
  after it did not run — and comes back with its reason and what the surf tab shows; to go on by
  looking again, changing what was wrong and sending the rest of the batch anew; and to hand the user
  only what is theirs to settle — a browser to attach, a hidden tab to show, an origin the host lists
  refuse, a credential to type, the Interactive WebSurf switch to turn on.

The host lists are the `websurf` section of the server settings file `assassin_settings.json`
(@ASSASSIN-SETTINGS), read at every use:
`{"websurf": {"allow": ["https://example.com", "https://*.example.org", "http://192.168.1.10:8080"], "block": ["https://*.bank.example"], "rounds": 60}}`.
An entry is an exact origin (the default port may be left out), `scheme://*.domain[:port]` for a
domain and its subdomains, or `*` for any origin; a wildcard never admits a private or link-local host. `block`
wins over `allow`; an empty or missing `allow` admits every public and loopback origin, so with no
settings WebSurf reaches the public web and the user's own machine, and no private network. Hosts are judged as written, the numeric IPv4 forms a
browser accepts (`127.1`, `2130706433`) included; names are not resolved. `rounds`, a positive
integer, bounds the rounds of a turn that surfs.
