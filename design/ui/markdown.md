# Markdown renderer

One renderer turns every markdown text the page shows into HTML: an item's statement, a file view, the user's and the AI's
chat messages — queued and delivered ones included — and the texts of a turn's steps. Its output reads the same wherever it
stands, styled by the `.md` rules of the one stylesheet, and so does what follows the HTML into the page: the diagrams. The panes
call it and never format markdown on their own.

## The subset

The text is escaped first and a small CommonMark subset is read over the escaped text: headings (each with its slug, the target
of a `#fragment` link), paragraphs, `**strong**` and `*em*`, inline code, fenced code, block quotes, `-`, `*` and numbered lists
nested by indent, pipe tables, rules, links and bare `http(s)` URLs. Raw HTML is never taken as markup but for the collapsible
section, `<details>` and `<summary>` written as on GitHub. An `http:`, `https:` or `mailto:` link opens in a new tab, any other
scheme shows as its label, a relative path is a link to a project file resolved against the folder of the file it stands in and
opening inside the block; `@UID` of a known item is a jump link.

A text the user typed keeps its line breaks: in a user message every line break inside a paragraph is a break of the shown text,
where a statement, a file or a reply joins the lines of a paragraph as markdown does.

## Diagrams

A fenced block tagged `mermaid` is a diagram. It shows as its source, a code block, until it is drawn, then as the drawing in its
place, scaled down to the width it stands in. A diagram that cannot be drawn — a syntax error, the library out of reach — keeps
its source, followed by a dim line `diagram not drawn: <reason>`. A diagram is drawn once per source and colour scheme in a tab: a
re-render of the log or a second block showing the same diagram takes the drawing kept, and a switch of the system's colour scheme
draws the diagrams shown anew in its theme (`default` light, `dark` dark).

The drawing library is Mermaid, pinned to one version and loaded from the jsDelivr CDN at the first diagram of a tab. The
`markdown` section of the server settings may name another copy of its ES module by an http or https URL, for a machine that does
not reach the CDN — `{"markdown": {"mermaid": "http://127.0.0.1:8000/mermaid.esm.min.mjs"}}`; anything else names the pinned one.

**Isolation.** The library is third-party code and the page holds the session token that runs turns, commands and edits, so the
library never runs in the page. It runs in the diagram frame, a hidden iframe served at `/markdown-frame` without the token and
sandboxed to scripts alone: an opaque origin reaching neither the page's DOM, its storage nor its token. The page posts the source
and the theme to the frame, which answers the drawing as SVG text or the error; the page shows the drawing as an image, an `<img>`
of the SVG as a data URL, so nothing in it runs or styles the page — labels are drawn as SVG text, not HTML, for that reason. The
frame's own policy admits its one nonced script and the library's origin; the page's policy admits the frame and nothing else new.

## Where it lives

`src/ai_scratcher/markdown.js` is inlined into the page ahead of the page's own script as the page is served, its version part of
the page's, so a change of it reloads open pages. `src/ai_scratcher/markdown_frame.html` is the frame page, the library's URL and
the nonce filled in at every request.
