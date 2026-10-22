# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/page.js` run by node against a minimal fake DOM recording the events dispatched -- [BROWSER-EXTENSION-QUERY],
[BROWSER-EXTENSION-FILL], [BROWSER-EXTENSION-MOUSE], [BROWSER-EXTENSION-REDACT], [BROWSER-EXTENSION-ORIGIN]."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "websurf-extension" / "page.js"
DRIVER = """
import { readFileSync } from 'node:fs';
import { pageAction } from %s;
const cfg = JSON.parse(readFileSync(0, 'utf8'));
let log = [], transfers = 0;
class FakeEvent {
  constructor(type, init = {}) {
    Object.assign(this, { bubbles: false, cancelable: false }, init);
    Object.assign(this, { type, kind: new.target.name, defaultPrevented: false });
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
}
// node's own Event stays: its MessageEvent, which the pointer's yields between moves use, extends it
for (const name of ['InputEvent', 'MouseEvent', 'PointerEvent', 'WheelEvent', 'DragEvent']) {
  globalThis[name] = { [name]: class extends FakeEvent {} }[name];
}
globalThis.DataTransfer = class DataTransfer { constructor() { this.id = ++transfers; } };
class FakeNode {
  constructor() { this.childNodes = []; this.parentNode = null; }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  appendChild(child) { child.parentNode = this; this.childNodes.push(child); return child; }
  remove() { if (this.parentNode) this.parentNode.childNodes.splice(this.parentNode.childNodes.indexOf(this), 1); this.parentNode = null; }
  contains(node) { for (; node; node = node.parentNode) if (node === this) return true; return false; }
  get isConnected() { return document.contains(this); }
  get textContent() { return this.childNodes.map((n) => (n.nodeType === 3 ? n.data : n.nodeType === 1 ? n.textContent : '')).join(''); }
  set textContent(text) { this.childNodes = []; this.appendChild(Object.assign(new FakeNode(), { nodeType: 3, data: text })); }
}
const FOCUSABLE = ['input', 'textarea', 'select', 'button'];
class FakeElement extends FakeNode {
  constructor(spec) {
    super();
    Object.assign(this, { nodeType: 1, localName: spec.tag, attrs: { ...spec.attrs }, rect: spec.rect || [0, 0, 0, 0], shadowRoot: null,
      disabled: !!spec.disabled, readOnly: !!spec.readOnly, isContentEditable: !!spec.editable, cancels: spec.cancel || [],
      overflow: spec.overflow || 'visible', extent: spec.extent || null, scrolled: spec.scrolled || null, style: {} });
  }
  get id() { return this.attrs.id || this.localName; }
  get attributes() { return Object.entries(this.attrs).map(([name, value]) => ({ name, value })); }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  get type() { return this.localName === 'textarea' ? 'textarea' : (this.attrs.type || 'text').toLowerCase(); }
  get tabIndex() {
    if (this.hasAttribute('tabindex')) return Number(this.attrs.tabindex);
    return FOCUSABLE.includes(this.localName) || (this.localName === 'a' && this.hasAttribute('href')) ? 0 : -1;
  }
  get clientWidth() { return this.rect[2]; }
  get clientHeight() { return this.rect[3]; }
  get scrollWidth() { return this.extent ? this.extent[0] : this.rect[2]; }
  get scrollHeight() { return this.extent ? this.extent[1] : this.rect[3]; }
  getBoundingClientRect() { const [left, top, width, height] = this.rect; return { left, top, width, height, right: left + width, bottom: top + height }; }
  scrollIntoView(options) { log.push(['scrollIntoView', this.id, options]); if (this.scrolled) this.rect = this.scrolled; }
  scrollBy(dx, dy) { log.push(['scrollBy', this.id, dx, dy]); }
  focus() { document.activeElement = this; log.push(['focus', this.id]); }
  blur() { document.activeElement = document.body; log.push(['blur', this.id]); }
  showPopover() { log.push(['showPopover', this.id]); }
  dispatchEvent(event) {
    const seen = { kind: event.kind };
    for (const key of ['bubbles', 'clientX', 'clientY', 'button', 'buttons', 'detail', 'deltaX', 'deltaY']) if (event[key] !== undefined) seen[key] = event[key];
    if (event.relatedTarget) seen.related = event.relatedTarget.id;
    if (event.dataTransfer) seen.transfer = event.dataTransfer.id;
    log.push([event.type, this.id, seen]);
    for (let n = this; n; n = event.bubbles ? n.parentNode : null) if (n.cancels && n.cancels.includes(event.type)) event.preventDefault();
    return !event.defaultPrevented;
  }
}
class FakeInput extends FakeElement {
  constructor(spec) { super(spec); this.current = spec.live ?? this.attrs.value ?? ''; this.checked = !!spec.checked; }
  get value() { return this.current; }
  set value(text) { this.current = String(text); log.push(['set value', this.id, this.current]); }
}
class FakeSelect extends FakeElement {
  get options() { return this.childNodes.filter((n) => n.localName === 'option'); }
  get value() { const chosen = this.options.find((o) => o.selected); return chosen ? chosen.value : ''; }
  set value(text) { for (const o of this.options) o.selected = o.value === text; log.push(['set value', this.id, text]); }
}
class FakeOption extends FakeElement {
  constructor(spec) { super(spec); this.selected = !!spec.selected; }
  get value() { return this.attrs.value ?? this.textContent; }
  get label() { return this.attrs.label ?? this.textContent; }
}
class FakeDocument extends FakeNode {
  constructor() { super(); this.nodeType = 9; this.activeElement = null; }
  get documentElement() { return this.childNodes[0]; }
  get body() { return all(this).find((n) => n.localName === 'body') || null; }
  createElement(tag) { return build({ tag }); }
  querySelectorAll(selector) { return all(this).filter(parse(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  elementFromPoint(x, y) {
    const hits = all(this).filter((n) => { const [l, t, w, h] = n.rect; return w > 0 && h > 0 && x >= l && x < l + w && y >= t && y < t + h; });
    return hits.pop() || null;
  }
}
const all = (root) => root.childNodes.filter((n) => n.nodeType === 1).flatMap((n) => [n, ...all(n)]);
function parse(selector) {
  const tests = String(selector).split(',').map((part) => {
    const m = /^([a-z][a-z0-9-]*|\\*)?((?:#[\\w-]+|\\.[\\w-]+|\\[[\\w-]+(?:="[^"]*")?\\])*)$/.exec(part.trim());
    if (!m || !(m[1] || m[2])) throw new SyntaxError(`'${selector}' is not a valid selector`);
    const conditions = [...m[2].matchAll(/#([\\w-]+)|\\.([\\w-]+)|\\[([\\w-]+)(?:="([^"]*)")?\\]/g)];
    return (el) => (!m[1] || m[1] === '*' || el.localName === m[1]) && conditions.every(([, id, cls, name, value]) =>
      id ? el.attrs.id === id : cls ? (el.attrs.class || '').split(' ').includes(cls) : value === undefined ? el.hasAttribute(name) : el.attrs[name] === value);
  });
  return (el) => tests.some((test) => test(el));
}
function build(spec) {
  if (typeof spec === 'string') return Object.assign(new FakeNode(), { nodeType: 3, data: spec });
  if (spec.comment !== undefined) return Object.assign(new FakeNode(), { nodeType: 8, data: spec.comment });
  const Kind = { input: FakeInput, textarea: FakeInput, select: FakeSelect, option: FakeOption }[spec.tag] || FakeElement;
  const el = new Kind(spec);
  for (const child of spec.children || []) el.appendChild(build(child));
  if (spec.shadow) {
    el.shadowRoot = Object.assign(new FakeNode(), { querySelectorAll(selector) { return all(this).filter(parse(selector)); } });
    for (const child of spec.shadow) el.shadowRoot.appendChild(build(child));
  }
  if (spec.tracked) Object.defineProperty(el, 'value', { get: () => el.current, set: (text) => log.push(['tracker', el.id, text]) });
  return el;
}
const document = new FakeDocument();
document.appendChild(build(cfg.dom));
document.activeElement = document.body;
document.visibilityState = cfg.visibility || 'visible';
// the top frame of a visible document of this origin, unless the run says otherwise; every call names that origin unless it names its own
const ORIGIN = 'https://example.org';
Object.assign(globalThis, {
  window: globalThis, document, innerWidth: 1000, innerHeight: 800, devicePixelRatio: 2,
  top: cfg.frame === 'sub' ? {} : globalThis, location: { origin: cfg.location || ORIGIN },
  getComputedStyle: (el) => ({ overflowX: el.overflow, overflowY: el.overflow }),
  scrollBy: (dx, dy) => log.push(['window.scrollBy', dx, dy]),
  // a frame out of sight, whose rendering the browser stops, never runs its animation frames
  requestAnimationFrame: (callback) => { log.push(['requestAnimationFrame']); if (!cfg.frozen) setTimeout(callback, 1); },
});
const runs = [];
for (const [action, options] of cfg.calls) {
  log = [];
  const start = performance.now();
  const result = await pageAction(action, { origin: ORIGIN, ...options });
  const layers = all(document).filter((n) => n.hasAttribute('popover')).map((layer) => layer.childNodes.map((box) => box.style.cssText));
  runs.push({ result, log, layers, ms: Math.round(performance.now() - start) });
}
const values = Object.fromEntries(all(document).filter((n) => n.attrs.id && ('current' in n || n.localName === 'select' || n.isContentEditable))
  .map((n) => [n.attrs.id, n.isContentEditable ? n.textContent : n.value]));
console.log(JSON.stringify({ runs, values }));
"""
SPEC = {"rect", "live", "checked", "selected", "disabled", "readOnly", "editable", "cancel", "overflow", "extent", "scrolled", "shadow",
        "tracked", "attrs"}


def _el(tag, *children, **given):
    """A fake DOM element: its tag, children and attributes, with the keywords of `SPEC` setting its live state and layout instead."""
    spec = {key: value for key, value in given.items() if key in SPEC}
    attrs = {**{key: value for key, value in given.items() if key not in SPEC}, **spec.pop("attrs", {})}
    return {"tag": tag, "attrs": attrs, "children": list(children), **spec}


def _doc(*body):
    """A document of a 1000 by 800 viewport whose body holds `body`."""
    return _el("html", _el("head"), _el("body", *body, rect=[0, 0, 1000, 800]), rect=[0, 0, 1000, 800])


def _page(dom, calls, **frame):
    """Return each call's result, event log, mask layers and duration, then the live values by element id, of `pageAction` calls run in
    order on one fake document under node -- the top frame of a visible `https://example.org` document unless `frame` gives its
    `location` origin, its `visibility` or a `frame` of "sub"."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "--input-type=module", "-e", DRIVER % json.dumps(PAGE.as_uri())],
                         input=json.dumps({"dom": dom, "calls": calls, **frame}), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _types(log, only=None):
    """The (type, element) pairs of a call's log, of the types in `only` when given."""
    return [(entry[0], entry[1]) for entry in log if only is None or entry[0] in only]


def _events(log, kind):
    """The details of the events of type `kind` in a call's log, in order."""
    return [entry[2] for entry in log if entry[0] == kind]


# -- query --------------------------------------------------------------------

@pytest.mark.syngate("BROWSER-EXTENSION-QUERY", "whole")
def test_a_query_without_a_selector_answers_the_whole_live_document_without_scripts_styles_and_comments():
    dom = _el("html",
              _el("head", _el("title", "Shop"), _el("meta", name="viewport", content="width=device-width"), _el("script", "var x = 1;"),
                  _el("style", "p { color: red }")),
              _el("body", {"comment": " build 7 "}, _el("h1", "  Hello \n  <World>  "), "\n   ", _el("p", "a  &  b", attrs={"class": "lead"}),
                  _el("noscript", "enable scripts"), _el("template", _el("p", "later")), _el("svg", _el("path", d="M0 0"), viewBox="0 0 1 1"),
                  _el("my-card", "light", shadow=[_el("b", "shadow")])))
    run = _page(dom, [("query", {})])
    assert run["runs"][0]["result"] == {
        "dom": '<html><head><title>Shop</title><meta name="viewport" content="width=device-width"></head><body><h1> Hello &lt;World&gt; </h1>'
               '<p class="lead">a &amp; b</p><svg viewBox="0 0 1 1"></svg><my-card><template shadowrootmode="open"><b>shadow</b></template>light'
               '</my-card></body></html>',
        "matches": 1, "truncated": False}


@pytest.mark.syngate("BROWSER-EXTENSION-QUERY", "selector")
def test_a_query_with_a_selector_answers_each_match_in_document_order_with_their_count():
    dom = _doc(_el("ul", _el("li", "one", attrs={"class": "item"}), _el("li", "two"), _el("li", _el("b", "three"), attrs={"class": "item"})))
    run = _page(dom, [("query", {"selector": "li.item"}), ("query", {"selector": ".none"}), ("query", {"selector": "##"})])
    found, none, invalid = (r["result"] for r in run["runs"])
    assert found == {"dom": '<li class="item">one</li>\n<li class="item"><b>three</b></li>', "matches": 2, "truncated": False}
    assert none == {"dom": "", "matches": 0, "truncated": False}
    assert list(invalid) == ["error"] and "not a valid selector" in invalid["error"]


@pytest.mark.syngate("BROWSER-EXTENSION-QUERY", "state")
def test_a_query_serializes_the_current_state_of_the_form_controls():
    dom = _doc(_el("form",
                   _el("input", id="name", attrs={"value": "old"}, live="Ann"),
                   _el("input", id="news", type="checkbox", attrs={"checked": ""}, checked=False),
                   _el("input", id="terms", type="radio", checked=True),
                   _el("select", _el("option", "Red", value="r", attrs={"selected": ""}), _el("option", "Blue", value="b", selected=True), id="color"),
                   _el("textarea", "draft", id="note", live="final text")))
    run = _page(dom, [("query", {"selector": "form"})])
    assert run["runs"][0]["result"]["dom"] == (
        '<form><input id="name" value="Ann"><input id="news" type="checkbox"><input id="terms" type="radio" checked>'
        '<select id="color"><option value="r">Red</option><option value="b" selected>Blue</option></select>'
        '<textarea id="note">final text</textarea></form>')


@pytest.mark.syngate("BROWSER-EXTENSION-QUERY", "limit")
def test_a_query_is_cut_to_its_limit_of_200000_characters_by_default_and_at_most():
    run = _page(_doc(_el("p", "x" * 250_000)), [("query", {"selector": "p", "max_chars": 12}), ("query", {"selector": "p", "max_chars": None}),
                                                ("query", {"selector": "p", "max_chars": 500_000})])
    cut, default, over = (r["result"] for r in run["runs"])
    assert cut == {"dom": "<p>xxxxxxxxx", "matches": 1, "truncated": True}
    assert len(default["dom"]) == 200_000 and default["truncated"] is True
    assert len(over["dom"]) == 200_000 and over["truncated"] is True
    whole = _page(_doc(_el("p", "short")), [("query", {"selector": "p", "max_chars": 12})])
    assert whole["runs"][0]["result"] == {"dom": "<p>short</p>", "matches": 1, "truncated": False}


# -- fill ---------------------------------------------------------------------

@pytest.mark.syngate("BROWSER-EXTENSION-FILL", "input")
def test_a_fill_sets_a_text_field_a_text_area_or_an_editable_element_as_typing_does():
    dom = _doc(_el("input", id="q", type="search", tracked=True, live="old"), _el("textarea", id="note"),
               _el("div", "draft", id="editor", contenteditable="true", editable=True))
    run = _page(dom, [("fill", {"selector": "#q", "value": "shoes"}), ("fill", {"selector": "textarea", "value": "two\nlines"}),
                      ("fill", {"selector": "#editor", "value": "Dear Ann"})])
    field, area, editor = run["runs"]
    assert [r["result"] for r in run["runs"]] == [{}, {}, {}]
    assert _types(field["log"]) == [("focus", "q"), ("set value", "q"), ("input", "q"), ("change", "q")]
    assert _types(area["log"]) == [("focus", "note"), ("set value", "note"), ("input", "note"), ("change", "note")]
    assert _types(editor["log"]) == [("focus", "editor"), ("input", "editor"), ("change", "editor")]
    for call in run["runs"]:
        assert all(entry[2]["bubbles"] is True for entry in call["log"] if entry[0] in ("input", "change"))
    assert run["values"] == {"q": "shoes", "note": "two\nlines", "editor": "Dear Ann"}


@pytest.mark.syngate("BROWSER-EXTENSION-FILL", "select")
def test_a_fill_of_a_select_picks_the_option_of_that_value_else_of_that_label():
    dom = _doc(_el("select", _el("option", "Red", value="r"), _el("option", " Deep blue ", value="b"), _el("option", "Green", value="g"), id="color"))
    run = _page(dom, [("fill", {"selector": "#color", "value": "b"}), ("fill", {"selector": "#color", "value": "Green"}),
                      ("fill", {"selector": "#color", "value": "Purple"})])
    by_value, by_label, missing = run["runs"]
    assert _types(by_value["log"]) == [("focus", "color"), ("set value", "color"), ("input", "color"), ("change", "color")]
    assert by_value["log"][1] == ["set value", "color", "b"] and by_label["log"][1] == ["set value", "color", "g"]
    assert "Purple" in missing["result"]["error"] and missing["log"] == []
    assert run["values"] == {"color": "g"}


@pytest.mark.syngate("BROWSER-EXTENSION-FILL", "refuse")
def test_a_fill_refuses_any_other_element_and_a_disabled_or_read_only_one():
    dom = _doc(_el("input", id="agree", type="checkbox"), _el("input", id="pick", type="file"), _el("button", "Go", id="go"),
               _el("div", "text", id="plain"), _el("input", id="off", disabled=True, live="kept"), _el("textarea", id="fixed", readOnly=True, live="kept"))
    selectors = ["#agree", "#pick", "#go", "#plain", "#off", "#fixed", "#missing", "##"]
    run = _page(dom, [("fill", {"selector": selector, "value": "x"}) for selector in selectors])
    for selector, call in zip(selectors, run["runs"]):
        assert list(call["result"]) == ["error"] and call["log"] == [], selector
    assert run["values"]["off"] == "kept" and run["values"]["fixed"] == "kept"


# -- mouse --------------------------------------------------------------------

BUTTONS = _doc(_el("button", "A", id="a", rect=[100, 100, 100, 40]), _el("button", "B", id="b", rect=[400, 100, 100, 40]),
               _el("a", "Far", id="far", href="/far", rect=[100, 2000, 100, 20], scrolled=[100, 380, 100, 20]))
MOVES = {"pointermove", "mousemove"}
PRESSES = {"pointerdown", "mousedown", "focus", "contextmenu", "pointerup", "mouseup", "click", "auxclick", "dblclick"}


@pytest.mark.syngate("BROWSER-EXTENSION-MOUSE", "move")
def test_a_move_is_a_path_of_pointer_moves_with_the_hover_transitions_it_crosses_from_where_the_pointer_was_left():
    run = _page(BUTTONS, [
        ("mouse", {"steps": [{"type": "move", "x": 150, "y": 120, "count": 4}]}),
        ("mouse", {"steps": [{"type": "move", "selector": "#b", "count": 2}]}),
        ("mouse", {"steps": [{"type": "down"}, {"type": "move", "x": 450, "y": 300, "count": 2}, {"type": "up"}]}),
        ("mouse", {"steps": [{"type": "pause", "ms": 60}]}),
        ("mouse", {"steps": [{"type": "move", "x": 1, "y": 1}] * 101}),
        ("mouse", {"steps": [{"type": "hover", "x": 1, "y": 1}]}),
    ])
    first, second, stroke, pause, too_many, unknown = run["runs"]
    assert _types(first["log"]) == [
        ("pointerover", "body"), ("pointerenter", "html"), ("pointerenter", "body"),
        ("mouseover", "body"), ("mouseenter", "html"), ("mouseenter", "body"), ("pointermove", "body"), ("mousemove", "body"),
        ("pointermove", "body"), ("mousemove", "body"), ("pointermove", "body"), ("mousemove", "body"),
        ("pointerout", "body"), ("pointerover", "a"), ("pointerenter", "a"), ("mouseout", "body"), ("mouseover", "a"), ("mouseenter", "a"),
        ("pointermove", "a"), ("mousemove", "a")]
    assert [(e["clientX"], e["clientY"]) for e in _events(first["log"], "pointermove")] == [(413, 330), (325, 260), (238, 190), (150, 120)]
    assert first["log"][13][2]["related"] == "body" and first["log"][12][2]["related"] == "a"
    assert [e["bubbles"] for e in _events(first["log"], "mouseenter")] == [False, False, False]

    assert [(e["clientX"], e["clientY"]) for e in _events(second["log"], "pointermove")] == [(300, 120), (450, 120)]
    assert ("pointerleave", "a") in _types(second["log"]) and ("pointerenter", "b") in _types(second["log"])

    assert [e["buttons"] for e in _events(stroke["log"], "pointermove")] == [1, 1]
    assert [e["buttons"] for e in _events(stroke["log"], "mousemove")] == [1, 1]
    assert _types(stroke["log"], PRESSES) == [("pointerdown", "b"), ("mousedown", "b"), ("focus", "b"), ("pointerup", "body"), ("mouseup", "body")]

    assert pause["result"] == {} and pause["ms"] >= 55 and pause["log"] == []
    assert "100" in too_many["result"]["error"] and too_many["log"] == []
    assert "hover" in unknown["result"]["error"] and unknown["log"] == []


@pytest.mark.syngate("BROWSER-EXTENSION-MOUSE", "click")
def test_a_click_fires_where_a_press_and_its_release_hit_one_element():
    run = _page(BUTTONS, [
        ("mouse", {"steps": [{"type": "click", "selector": "#a"}]}),
        ("mouse", {"steps": [{"type": "down", "selector": "#a"}, {"type": "up", "selector": "#b"}]}),
        ("mouse", {"steps": [{"type": "click", "selector": "#a", "button": "right"}]}),
        ("mouse", {"steps": [{"type": "click", "selector": "#a", "button": "middle"}]}),
        ("mouse", {"steps": [{"type": "dblclick", "x": 450, "y": 120}]}),
        ("mouse", {"steps": [{"type": "click", "selector": "#far"}]}),
    ])
    left, apart, right, middle, double, far = run["runs"]
    assert len(_events(left["log"], "pointermove")) == 10
    assert _types(left["log"], PRESSES) == [("pointerdown", "a"), ("mousedown", "a"), ("focus", "a"), ("pointerup", "a"), ("mouseup", "a"), ("click", "a")]
    down, up, click = _events(left["log"], "pointerdown")[0], _events(left["log"], "pointerup")[0], _events(left["log"], "click")[0]
    assert (down["button"], down["buttons"], up["buttons"]) == (0, 1, 0)
    assert (click["clientX"], click["clientY"], click["detail"], click["kind"]) == (150, 120, 1, "PointerEvent")

    assert _types(apart["log"], PRESSES) == [("pointerdown", "a"), ("mousedown", "a"), ("focus", "a"), ("pointerup", "b"), ("mouseup", "b")]
    assert _types(right["log"], PRESSES) == [("pointerdown", "a"), ("mousedown", "a"), ("contextmenu", "a"), ("pointerup", "a"), ("mouseup", "a")]
    assert _events(right["log"], "mousedown")[0]["buttons"] == 2
    assert _types(middle["log"], PRESSES) == [("pointerdown", "a"), ("mousedown", "a"), ("pointerup", "a"), ("mouseup", "a"), ("auxclick", "a")]
    assert _types(double["log"], PRESSES) == [("pointerdown", "b"), ("mousedown", "b"), ("focus", "b"), ("pointerup", "b"), ("mouseup", "b"), ("click", "b")] * 2 + [("dblclick", "b")]
    assert [e["detail"] for e in _events(double["log"], "click") + _events(double["log"], "dblclick")] == [1, 2, 2]

    assert far["log"][0] == ["scrollIntoView", "far", {"block": "center", "inline": "center", "behavior": "instant"}]
    assert (_events(far["log"], "click")[0]["clientX"], _events(far["log"], "click")[0]["clientY"]) == (150, 390)


@pytest.mark.syngate("BROWSER-EXTENSION-MOUSE", "drag")
def test_a_move_pressed_on_a_draggable_element_plays_an_html5_drag_with_one_shared_data_transfer():
    dom = _doc(_el("div", _el("span", "Card", id="title", rect=[110, 310, 50, 20]), id="card", draggable="true", rect=[100, 300, 100, 50]),
               _el("div", id="zone", rect=[600, 300, 200, 100], cancel=["dragover"]), _el("div", id="bin", rect=[600, 500, 200, 100]))
    run = _page(dom, [
        ("mouse", {"steps": [{"type": "down", "selector": "#title"}, {"type": "move", "selector": "#zone", "count": 3}, {"type": "up"}]}),
        ("mouse", {"steps": [{"type": "down", "selector": "#card"}, {"type": "move", "selector": "#bin", "count": 2}, {"type": "up"}]}),
    ])
    dropped, refused = run["runs"]
    drag_events = {"dragstart", "drag", "dragenter", "dragover", "dragleave", "drop", "dragend"}
    assert _types(dropped["log"], drag_events) == [
        ("dragstart", "card"), ("drag", "card"), ("dragenter", "body"), ("dragover", "body"), ("drag", "card"), ("dragover", "body"),
        ("drag", "card"), ("dragenter", "zone"), ("dragleave", "body"), ("dragover", "zone"), ("drop", "zone"), ("dragend", "card")]
    assert {entry[2]["transfer"] for entry in dropped["log"] if entry[0] in drag_events} == {1}
    started = [entry[0] for entry in dropped["log"]].index("dragstart")
    assert not [entry for entry in dropped["log"][started:] if entry[0] in MOVES | {"pointerup", "mouseup", "click"}]
    assert _events(dropped["log"], "drop")[0]["clientX"] == 700

    assert _types(refused["log"], drag_events) == [
        ("dragstart", "card"), ("drag", "card"), ("dragenter", "body"), ("dragover", "body"),
        ("drag", "card"), ("dragenter", "bin"), ("dragleave", "body"), ("dragover", "bin"), ("dragleave", "bin"), ("dragend", "card")]
    assert {entry[2]["transfer"] for entry in refused["log"] if entry[0] in drag_events} == {2}


@pytest.mark.syngate("BROWSER-EXTENSION-MOUSE", "wheel")
def test_a_wheel_turn_fires_at_the_pointer_and_scrolls_the_nearest_scrollable_ancestor_unless_cancelled():
    dom = _doc(_el("div", _el("div", "row", id="row", rect=[100, 100, 300, 20]), id="list", rect=[100, 100, 300, 200], overflow="auto", extent=[300, 1000]),
               _el("div", _el("div", "cell", id="cell", rect=[500, 100, 300, 20]), id="pane", rect=[500, 100, 300, 200], overflow="hidden", extent=[300, 1000]),
               _el("div", id="map", rect=[100, 400, 300, 200], cancel=["wheel"]))
    run = _page(dom, [
        ("mouse", {"steps": [{"type": "wheel", "selector": "#row", "dy": 120}]}),
        ("mouse", {"steps": [{"type": "wheel", "selector": "#cell", "dy": 50}]}),
        ("mouse", {"steps": [{"type": "wheel", "selector": "#map", "dx": 10, "dy": 40}]}),
        ("mouse", {"steps": [{"type": "move", "selector": "#row"}, {"type": "wheel", "dx": 0, "dy": -60}]}),
    ])
    inner, page, cancelled, here = run["runs"]
    scrolls = lambda log: [entry for entry in log if entry[0] in ("scrollBy", "window.scrollBy")]
    wheel = _events(inner["log"], "wheel")[0]
    assert (wheel["clientX"], wheel["clientY"], wheel["deltaX"], wheel["deltaY"], wheel["kind"]) == (250, 110, 0, 120, "WheelEvent")
    assert _types(inner["log"], {"wheel"}) == [("wheel", "row")] and scrolls(inner["log"]) == [["scrollBy", "list", 0, 120]]
    assert scrolls(page["log"]) == [["window.scrollBy", 0, 50]]
    assert _types(cancelled["log"], {"wheel"}) == [("wheel", "map")] and scrolls(cancelled["log"]) == []
    assert _types(here["log"], {"wheel"}) == [("wheel", "row")] and scrolls(here["log"]) == [["scrollBy", "list", 0, -60]]


# -- redaction ----------------------------------------------------------------

SECRETS = ("hunter2", "tok-form", "tok-meta", "4111111111111111", "123456")


@pytest.mark.syngate("BROWSER-EXTENSION-REDACT", "query")
def test_a_query_stubs_the_value_of_every_sensitive_element():
    dom = _el("html",
              _el("head", _el("meta", name="csrf-token", content="tok-meta"), _el("meta", name="description", content="A shop")),
              _el("body", _el("form", _el("input", id="user", live="ann"), _el("input", id="pass", type="password", live="hunter2"),
                              _el("input", type="hidden", name="csrf", attrs={"value": "tok-form"}),
                              _el("input", id="card", autocomplete="cc-number", live="4111111111111111"),
                              _el("textarea", id="otp", autocomplete="one-time-code", live="123456"))))
    dom_text = _page(dom, [("query", {})])["runs"][0]["result"]["dom"]
    assert not [secret for secret in SECRETS if secret in dom_text]
    for kept in ('<meta name="csrf-token" content="[redacted]">', '<meta name="description" content="A shop">', '<input id="user" value="ann">',
                 '<input id="pass" type="password" value="[redacted]">', '<input type="hidden" name="csrf" value="[redacted]">',
                 '<input id="card" autocomplete="cc-number" value="[redacted]">', '<textarea id="otp" autocomplete="one-time-code">[redacted]</textarea>'):
        assert kept in dom_text, kept


@pytest.mark.syngate("BROWSER-EXTENSION-REDACT", "screenshot")
def test_a_screenshot_is_taken_with_an_opaque_box_over_every_visible_sensitive_element():
    dom = _doc(_el("input", id="pass", type="password", rect=[100, 200, 300, 30]), _el("input", id="user", rect=[100, 150, 300, 30]),
               _el("input", type="hidden", name="csrf"), _el("input", id="below", type="password", rect=[100, 5000, 300, 30]),
               _el("input", id="card", autocomplete="cc-number", rect=[100, 300, 300, 30]),
               _el("login-box", shadow=[_el("input", id="inner", type="password", rect=[100, 400, 300, 30])]))
    run = _page(dom, [("mask", {"on": True}), ("mask", {"on": False})])
    masked, unmasked = run["runs"]
    assert masked["result"] == {"viewport": {"width": 1000, "height": 800}, "scale": 2, "masked": 3}
    [boxes] = masked["layers"]
    box = lambda css: tuple(int(re.search(rf"{side}:(\d+)px", css)[1]) for side in ("left", "top", "width", "height"))
    assert sorted(box(css) for css in boxes) == [(100, 200, 300, 30), (100, 300, 300, 30), (100, 400, 300, 30)]
    assert all("background:#000" in css for css in boxes)
    assert ["showPopover", "div"] in masked["log"]
    assert unmasked["layers"] == [] and unmasked["result"]["viewport"] == {"width": 1000, "height": 800}


@pytest.mark.syngate("BROWSER-EXTENSION-REDACT", "fill")
def test_a_fill_never_fills_a_sensitive_element():
    dom = _doc(_el("input", id="pass", type="password"), _el("input", id="token", type="hidden", attrs={"value": "tok-form"}),
               _el("input", id="card", type="tel", autocomplete="billing cc-number"), _el("textarea", id="otp", autocomplete="one-time-code"))
    run = _page(dom, [("fill", {"selector": f"#{name}", "value": "typed-by-ai"}) for name in ("pass", "token", "card", "otp")])
    for call in run["runs"]:
        assert "sensitive" in call["result"]["error"] and call["log"] == []
    assert run["values"] == {"pass": "", "token": "tok-form", "card": "", "otp": ""}


@pytest.mark.syngate("BROWSER-EXTENSION-SCREENSHOT", "paint")
def test_the_masks_are_laid_without_awaiting_a_frame_and_painted_by_two_frames_of_the_visible_top_frame_alone():
    dom = _doc(_el("input", id="pass", type="password", rect=[100, 200, 300, 30]))
    framed = _page(dom, [("mask", {"on": True})], frame="sub", frozen=True)  # an iframe scrolled out of sight
    assert framed["runs"][0]["result"]["masked"] == 1 and ["requestAnimationFrame"] not in framed["runs"][0]["log"]
    painted = _page(dom, [("mask", {"on": True}), ("paint", {})])
    assert painted["runs"][1]["result"] == {} and painted["runs"][1]["log"].count(["requestAnimationFrame"]) == 2
    for refused, frame in (({"hidden": "its page is not visible"}, {"visibility": "hidden"}),
                           ({"error": _elsewhere("https://example.org", "https://other.example")}, {})):
        run = _page(dom, [("paint", {"origin": "https://other.example"} if "error" in refused else {})], frozen=True, **frame)
        assert run["runs"][0]["result"] == refused and run["runs"][0]["log"] == []  # never left awaiting a page it may not paint


# -- origin -------------------------------------------------------------------

def _elsewhere(here, asked):
    """The refusal of a page action asked for `asked` in a document of `here`."""
    return f"the surf tab's page is on {here}, not {asked}: check it and repeat the call with its origin"


@pytest.mark.syngate("BROWSER-EXTENSION-ORIGIN", "check")
def test_a_page_action_plays_only_in_a_top_level_document_of_the_origin_it_names():
    dom = _doc(_el("input", id="q", rect=[100, 100, 200, 30]), _el("input", id="pass", type="password", rect=[100, 200, 200, 30]))
    other = {"origin": "https://other.example"}
    run = _page(dom, [("query", other), ("fill", {"selector": "#q", "value": "x", **other}), ("mouse", {"steps": [{"type": "click", "selector": "#q"}], **other}),
                      ("mask", {"on": True, **other}), ("query", {"selector": "#q"}), ("mask", {"on": True})])
    *refused, queried, masked = run["runs"]
    for call in refused:
        assert call["result"] == {"error": _elsewhere("https://example.org", "https://other.example")} and call["log"] == [] and call["layers"] == []
    assert queried["result"] == {"dom": '<input id="q" value="">', "matches": 1, "truncated": False}
    assert masked["result"]["masked"] == 1 and run["values"]["q"] == ""

    opaque = _page(dom, [("query", {}), ("mouse", {"steps": [{"type": "click", "selector": "#q"}]})], location="null")
    assert [call["result"] for call in opaque["runs"]] == [{"error": _elsewhere("a page of no origin", "https://example.org")}] * 2
    assert opaque["runs"][1]["log"] == []

    framed = _page(dom, [("mask", {"on": True, **other})], frame="sub")
    assert framed["runs"][0]["result"]["masked"] == 1
