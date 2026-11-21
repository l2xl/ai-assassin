// Open Trader
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

// The markdown renderer of the AI Assassin page (design/ui/markdown.md): one set of rules for every markdown text the page shows, and the
// diagrams drawn in the sandboxed diagram frame. Inlined into the page as it is served, ahead of the page's own script, whose `esc` and
// `state` it reads at call time.
"use strict";

// ---- markdown: escape first, then a small CommonMark subset over the escaped text; never raw HTML --

// A known item's UID written `@UID` (or the older `[UID]`) is a jump link to its block; the text is left as written, escaped already.
const UID_TAG_RE = /\[([A-Z](?:[A-Z0-9_-]*[A-Z0-9])?)\]|@([A-Z](?:[A-Z0-9_-]*[A-Z0-9])?)(?![\w-])/g;
const uidLink = (uid) => (state.model.items[uid] ? `<a class="jump" data-uid="${esc(uid)}">@${esc(uid)}</a>` : "@" + esc(uid));
const jumps = (html) =>html.replace(UID_TAG_RE, (m, tagged, at) => state.model.items[tagged || at] ? `<a class="jump" data-uid="${tagged || at}">${tagged || m}</a>` : m);
const dirname = (path) => path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
const slug = (text) => text.toLowerCase().replace(/<[^>]*>/g, "").replace(/&[a-z#0-9]+;/g, "").replace(/[^\w\- ]/g, "").trim().replace(/\s+/g, "-");

function resolvePath(base, rel) {
  const parts = rel.startsWith("/") || !base ? [] : base.split("/");
  for (const seg of rel.split("/")) {
    if (!seg || seg === ".") continue;
    if (seg === "..") parts.pop(); else parts.push(seg);
  }
  return parts.join("/");
}

// Links point into the project unless they carry an allowed scheme; other schemes degrade to text.
function linkHtml(label, href, base) {
  if (/^(https?:|mailto:)/i.test(href)) return `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}</a>`;
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return esc(label);
  const [target, frag] = href.split("#"), path = target ? resolvePath(base, target) : "";
  return `<a class="filelink" data-file="${esc(path)}" data-frag="${esc(frag || "")}" title="${esc(path)}">${esc(label)}</a>`;
}

function inline(raw, base) {
  const parts = [], hold = (html) => { parts.push(html); return `\u0000${parts.length - 1}\u0000`; };
  const text = raw.replace(/`([^`\n]+)`/g, (_, code) => hold(`<code>${esc(code)}</code>`))
    .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_, label, href) => hold(linkHtml(label, href, base)))
    .replace(/(^|[\s(])(https?:\/\/[^\s<>)]+)/g, (_, pre, url) => pre + hold(linkHtml(url, url, base)));
  return jumps(esc(text)).replace(/\*\*(\S(?:.*?\S)?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^\w*])\*(\S(?:[^*\n]*?\S)?)\*(?![\w*])/g, "$1<em>$2</em>")
    .replace(/\u0000(\d+)\u0000/g, (_, i) => parts[i]);
}

// A collapsible section is written as on GitHub: a `<details>` line (`<details open>` shown expanded), its `<summary>…</summary>` -- on
// the same line or the next -- then markdown up to the matching `</details>` line; it is the only markup of the text taken as such.
// A fence tagged `mermaid` is a diagram: its source in a code block the diagrams below draw over. A `typed` text -- what the user wrote --
// keeps every line break of its paragraphs.
const FOLD_OPEN = /^\s*<details(\s+open)?\s*>\s*(?:<summary>(.*?)<\/summary>)?\s*$/i, FOLD_EDGE = /^\s*<\/?details[\s>]/i;
function md(text, base, typed = false) {
  const lines = text.split("\n"), out = [];
  const listAt = (line) => /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(line);
  const blockStart = (line) => /^(```|#{1,6}\s|>|\||(-{3,}|\*{3,})\s*$)/.test(line) || listAt(line) || FOLD_EDGE.test(line);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    const fold = FOLD_OPEN.exec(line);
    if (fold) {
      const buf = [], at = i;
      let summary = fold[2], depth = 1, fence = false;
      for (i++; i < lines.length; i++) {
        const l = lines[i];
        if (l.startsWith("```")) fence = !fence;
        if (!fence) {
          const named = summary == null && !buf.some((b) => b.trim()) && /^\s*<summary>(.*?)<\/summary>\s*$/i.exec(l);
          if (named) { summary = named[1]; continue; }
          if (FOLD_OPEN.test(l)) depth++;
          else if (/^\s*<\/details>\s*$/i.test(l) && !--depth) { i++; break; }
        }
        buf.push(l);
      }
      out.push(`<details class="md-fold" data-at="${at}"${fold[1] ? " open" : ""}><summary>${inline(summary?.trim() || "details", base)}</summary>${md(buf.join("\n"), base, typed)}</details>`);
      continue;
    }
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim().split(/\s+/)[0].toLowerCase(), buf = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) buf.push(lines[i]);
      i++;
      const code = `<pre><code>${esc(buf.join("\n"))}</code></pre>`;
      out.push(lang === "mermaid" ? `<div class="md-mermaid">${code}</div>` : code);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) { const html = inline(heading[2], base); out.push(`<h${heading[1].length} data-slug="${esc(slug(html))}">${html}</h${heading[1].length}>`); i++; continue; }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (line.startsWith(">")) {
      const buf = [];
      for (; i < lines.length && lines[i].startsWith(">"); i++) buf.push(lines[i].replace(/^>\s?/, ""));
      out.push(`<blockquote>${md(buf.join("\n"), base, typed)}</blockquote>`);
      continue;
    }
    if (line.startsWith("|") && /^\|?\s*:?-+/.test(lines[i + 1] || "")) {
      const cells = (row) => row.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim(), base));
      out.push(`<table><tr>${cells(line).map((c) => `<th>${c}</th>`).join("")}</tr>`);
      for (i += 2; i < lines.length && lines[i].startsWith("|"); i++) out.push(`<tr>${cells(lines[i]).map((c) => `<td>${c}</td>`).join("")}</tr>`);
      out.push("</table>");
      continue;
    }
    if (listAt(line)) {
      const stack = [];
      for (; i < lines.length && !/^\s*$/.test(lines[i]) && !FOLD_EDGE.test(lines[i]); i++) {
        const at = listAt(lines[i]);
        if (!at) { out.push((typed ? "<br>" : " ") + inline(lines[i].trim(), base)); continue; }
        const indent = at[1].length, tag = /\d/.test(at[2]) ? "ol" : "ul";
        while (stack.length && indent < stack[stack.length - 1].indent) out.push(`</li></${stack.pop().tag}>`);
        if (stack.length && indent === stack[stack.length - 1].indent) out.push("</li>");
        else { stack.push({ indent, tag }); out.push(`<${tag}>`); }
        out.push(`<li>${inline(at[3], base)}`);
      }
      while (stack.length) out.push(`</li></${stack.pop().tag}>`);
      continue;
    }
    const buf = [];
    for (; i < lines.length && !/^\s*$/.test(lines[i]) && !(buf.length && blockStart(lines[i])); i++) buf.push(lines[i].trim());
    out.push(`<p>${typed ? buf.map((l) => inline(l, base)).join("<br>") : inline(buf.join(" "), base)}</p>`);
  }
  return out.join("");
}

// ---- diagrams: drawn by the library in the sandboxed diagram frame, taken back as SVG text and shown as images, kept per source and theme --

const DIAGRAM_FRAME = "/markdown-frame", DARK = matchMedia("(prefers-color-scheme: dark)");
const diagrams = new Map(), diagramWaits = new Map();  // theme + source -> the drawing or its promise; message id -> its answer's taker
let diagramFrame = null, diagramSerial = 0;
const diagramTheme = () => (DARK.matches ? "dark" : "default");

// The diagram frame, made at the first diagram: a hidden iframe of an opaque origin, which says when its library listens.
function diagramRenderer() {
  if (!diagramFrame) diagramFrame = new Promise((ready) => {
    const frame = document.createElement("iframe");
    frame.className = "md-diagram-frame";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("aria-hidden", "true");
    frame.tabIndex = -1;
    frame.title = "diagram renderer";
    addEventListener("message", (event) => {
      const said = event.data;
      if (event.source !== frame.contentWindow || !said || typeof said !== "object") return;
      if (said.ready) ready(frame);
      else if (diagramWaits.has(said.id)) { diagramWaits.get(said.id)(said); diagramWaits.delete(said.id); }
    });
    frame.src = DIAGRAM_FRAME;
    document.body.append(frame);
  });
  return diagramFrame;
}

// The drawing of `source` in `theme` -- {svg} or {error} -- asked of the frame once and kept for the tab.
function drawDiagram(source, theme) {
  const key = theme + "\n" + source;
  if (!diagrams.has(key)) diagrams.set(key, diagramRenderer().then((frame) => new Promise((done) => {
    const id = ++diagramSerial;
    diagramWaits.set(id, done);
    frame.contentWindow.postMessage({ id, source, theme }, "*");
  })).then((said) => {
    const drawn = typeof said.svg === "string" ? { svg: said.svg } : { error: String(said.error || "no drawing came back") };
    diagrams.set(key, drawn);
    return drawn;
  }));
  return diagrams.get(key);
}

// Show the drawing in place of the diagram's source, or the source followed by the reason it was not drawn.
function placeDiagram(box, drawn, theme) {
  box.dataset.theme = theme;
  box.querySelector(":scope > .md-diagram, :scope > .md-diagram-error")?.remove();
  const source = box.querySelector(":scope > pre");
  if (drawn.svg != null) {
    const image = document.createElement("img");
    image.className = "md-diagram";
    image.alt = "diagram";
    image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(drawn.svg);
    source.hidden = true;
    box.append(image);
  } else {
    const note = document.createElement("div");
    note.className = "md-diagram-error";
    note.textContent = "diagram not drawn: " + drawn.error;
    source.hidden = false;
    box.append(note);
  }
}

// Draw the diagrams under `root` not yet shown in the current theme: a kept drawing at once, the others as they come back.
function renderDiagrams(root) {
  const theme = diagramTheme();
  for (const box of root.querySelectorAll(".md-mermaid")) {
    if (box.dataset.theme === theme || !box.querySelector(":scope > pre")) continue;
    const source = box.querySelector(":scope > pre").textContent, kept = diagrams.get(theme + "\n" + source);
    if (kept && !(kept instanceof Promise)) placeDiagram(box, kept, theme);
    else drawDiagram(source, theme).then((drawn) => { if (box.isConnected && box.dataset.theme !== theme) placeDiagram(box, drawn, theme); });
  }
}

// Whatever path puts rendered markdown into the page, its diagrams are drawn; a switch of the colour scheme draws them anew.
new MutationObserver((records) => {
  for (const record of records) for (const node of record.addedNodes) if (node.nodeType === 1 && (node.matches(".md-mermaid") || node.querySelector(".md-mermaid"))) renderDiagrams(node.parentElement || node);
}).observe(document.documentElement, { childList: true, subtree: true });
DARK.addEventListener("change", () => renderDiagrams(document));
