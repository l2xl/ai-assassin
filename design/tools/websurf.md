# WebSurf tool

**The user's browser goes through the WebSurf tool** (`prompts/websurf.md`, `websurf`), always
offered: `{"tool": "websurf", "action": "open", "url": "…"}` drives the surf tab of the browser
extension attached to the server, its answer coming back like a query's result, the page info and
DOM fenced as untrusted and a screenshot as an image of the next prompt — the one case where a
results prompt carries images, which the connection receives with the text.
