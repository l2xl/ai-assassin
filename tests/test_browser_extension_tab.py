# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/surf.js`, with `events.js` watching as the background wires them, run by node against a mock `browser` whose tabs
navigate on timers -- [BROWSER-EXTENSION-TAB], [BROWSER-EXTENSION-OPEN], [BROWSER-EXTENSION-CLOSE], [BROWSER-EXTENSION-HIDDEN],
[BROWSER-EXTENSION-ORIGIN], [BROWSER-EXTENSION-SCREENSHOT], [BROWSER-EXTENSION-MOUSE], [BROWSER-EXTENSION-BRIDGE]."""

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "websurf-extension"
HTML = "text/html; charset=utf-8"
DRIVER = """
import { surf } from %(surf)s;
import { watchSurfTab } from %(events)s;
const cfg = JSON.parse(process.argv[1]);
const calls = [], checks = [], frames = [];
const event = () => {
  const listeners = new Set();
  return { listeners, addListener: (l) => listeners.add(l), removeListener: (l) => listeners.delete(l),
           fire: (...args) => [...listeners].forEach((l) => l(...args)) };
};
const nav = {};
for (const name of ['onBeforeNavigate', 'onCommitted', 'onCompleted', 'onErrorOccurred', 'onHistoryStateUpdated', 'onReferenceFragmentUpdated']) nav[name] = event();
const responses = event(), removed = event();
const shown = { windowId: 1, index: 0, active: true, hidden: false, splitViewId: -1 };
const tabs = new Map(Object.entries(cfg.tabs).map(([id, tab]) => [Number(id), { id: Number(id), ...shown, ...tab }]));
const windows = new Map(Object.entries(cfg.windows || {}).map(([id, win]) => [Number(id), win]));
let nextId = 100;
// a navigation as the browser plays it: started, then committed -- its URL the tab's from then on -- answered and loaded, unless it hangs
const navigate = (tabId, url, timing = {}) => setTimeout(() => {
  nav.onBeforeNavigate.fire({ tabId, frameId: 0, url });
  if (cfg.hang) return;
  setTimeout(() => {
    if (!tabs.has(tabId)) return;
    const final = (cfg.redirects || {})[url] || url;
    Object.assign(tabs.get(tabId), { url: final, title: `Title of ${final}`, pendingUrl: undefined });
    nav.onCommitted.fire({ tabId, frameId: 0, url: final });
    responses.fire({ tabId, frameId: 0, type: 'main_frame', url: final, statusCode: cfg.status || 200,
                     responseHeaders: [{ name: 'Content-Type', value: 'text/html; charset=utf-8' }] });
    nav.onCompleted.fire({ tabId, frameId: 0, url: final });
  }, timing.load ?? 5);
}, timing.start ?? 1);
const close = (id) => {
  if (!tabs.has(id)) return;
  const tab = tabs.get(id);
  tabs.delete(id);
  removed.fire(id, { windowId: tab.windowId, isWindowClosing: false });
};
const api = {
  tabs: {
    query: async () => cfg.query || [],
    get: async (id) => { if (!tabs.has(id)) throw new Error(`no tab ${id}`); return { ...tabs.get(id) }; },
    create: async (props) => {
      calls.push(['tabs.create', props]);
      const split = props.splitWithTabId === undefined ? -1 : 1;
      // Chrome tells the URL of the navigation not yet committed as pendingUrl, Firefox shows about:blank meanwhile
      const loading = cfg.firefox ? { url: 'about:blank' } : { url: '', pendingUrl: props.url };
      const tab = { id: nextId++, ...shown, windowId: props.windowId ?? 2, index: props.index ?? 0, active: props.active ?? true, splitViewId: split, ...loading, title: '' };
      tabs.set(tab.id, tab);
      navigate(tab.id, props.url, cfg.timing);
      return { ...tab };
    },
    update: async (id, props) => { calls.push(['tabs.update', id, props]); if (props.url) navigate(id, props.url, cfg.timing); return { ...tabs.get(id) }; },
    remove: async (id) => { calls.push(['tabs.remove', id]); if (!tabs.has(id)) throw new Error(`no tab ${id}`); close(id); },
    captureVisibleTab: async (windowId, options) => { calls.push(['tabs.captureVisibleTab', windowId, options]); return `data:image/png;base64,${btoa('capture')}`; },
    onRemoved: removed,
  },
  windows: { get: async (id) => { checks.push(['windows.get', id]); return { id, state: 'normal', ...windows.get(id) }; } },
  webNavigation: nav,
  webRequest: { onCompleted: responses },
  scripting: {
    executeScript: async ({ target, func, args }) => {
      calls.push(['scripting.executeScript', target, func.name, ...args]);
      const reply = (cfg.inPage || {})[args[0] === 'mask' ? `mask ${args[1].on}` : args[0]] || {};
      if (reply.navigate) navigate(target.tabId, reply.navigate.url, reply.navigate);
      if (reply.close !== undefined) setTimeout(() => close(target.tabId), reply.close);
      if (reply.hang) return new Promise(() => {});
      const injections = [{ frameId: 0, result: reply.result || {} }];
      if (target.allFrames) injections.unshift({ frameId: 4, result: { viewport: { width: 300, height: 150 }, scale: 1, masked: 0 } });
      return injections;
    },
  },
};
if (cfg.split) api.tabs.createSplit = async () => ({});
// the capture decoded, scaled on a canvas and encoded anew, each step told
globalThis.createImageBitmap = async (blob) => {
  calls.push(['createImageBitmap', blob.type, await blob.text()]);
  const [width, height] = cfg.captured || [2560, 1440];
  return { width, height, close: () => calls.push(['bitmap.close']) };
};
globalThis.OffscreenCanvas = class {
  constructor(width, height) { Object.assign(this, { width, height }); }
  getContext(kind) { return { drawImage: (bitmap, ...box) => calls.push(['drawImage', kind, ...box]) }; }
  async convertToBlob(options) { calls.push(['convertToBlob', options]); return new Blob([`jpeg ${this.width}x${this.height}`], { type: options.type }); }
};
const state = { tabId: null, response: null, page: null, placement: null, ...cfg.state };
watchSurfTab(api, state, (frame) => frames.push(frame));
const count = () => [...Object.values(nav), responses, removed].reduce((sum, e) => sum + e.listeners.size, 0);
const before = count();
// the surf tab of the session of the harness at this origin
const config = { origin: 'http://127.0.0.1:8712' };
const results = [];
for (const [index, request] of cfg.requests.entries()) {
  // what goes on before the request: the AI waiting for its page, the user showing the tab again or closing it
  const change = (cfg.changes || {})[index] || {};
  if (change.waitMs) await new Promise((resolve) => setTimeout(resolve, change.waitMs));
  for (const [id, props] of Object.entries(change.tabs || {})) Object.assign(tabs.get(Number(id)), props);
  for (const [id, props] of Object.entries(change.windows || {})) windows.set(Number(id), props);
  for (const id of change.close || []) close(id);
  const start = performance.now();
  const result = await surf(api, request, config, state).catch((e) => ({ thrown: String(e.message) }));
  results.push({ ...result, ms: Math.round(performance.now() - start) });
}
await new Promise((resolve) => setTimeout(resolve, cfg.afterMs ?? 20));
console.log(JSON.stringify({ results, calls, checks, frames, tabId: state.tabId, listeners: [before, count()] }));
"""


def _surf(requests, tabs=None, state=None, **cfg):
    """Return the results with their duration in ms, the recorded browser calls, the window checks apart, the page frames, the final
    surf tab id and the navigation listeners before and after of surf requests run under node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"requests": requests, "tabs": tabs or {}, "state": state or {}, **cfg}
    script = DRIVER % {"surf": json.dumps((EXTENSION / "surf.js").as_uri()), "events": json.dumps((EXTENSION / "events.js").as_uri())}
    out = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(cfg)], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


def _in_page(action, options, visibility, origin):
    """Return what `pageAction` of `websurf-extension/page.js` answers in the top frame of a document of that visibility and origin."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (f"import {{ pageAction }} from {json.dumps((EXTENSION / 'page.js').as_uri())};\n"
              "const [action, options, visibilityState, origin] = JSON.parse(process.argv[1]);\n"
              "Object.assign(globalThis, { window: globalThis, top: globalThis, document: { visibilityState }, location: { origin } });\n"
              "console.log(JSON.stringify(await pageAction(action, options)));\n")
    out = subprocess.run([node, "--input-type=module", "-e", script, json.dumps([action, options, visibility, origin])],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def _page(url, title=None, status=200, content_type=HTML):
    """The page info the mock browser reports for `url` once loaded."""
    return {"url": url, "title": f"Title of {url}" if title is None else title, "status": status, "content_type": content_type}


def _pending(url):
    """The page info of a document of `url` whose navigation has started but not committed."""
    return {"url": url, "title": "", "status": None, "content_type": None}


def _plain(results):
    """The results without their durations."""
    return [{key: value for key, value in result.items() if key != "ms"} for result in results]


def _hidden(result, why):
    """Whether `result` is the hidden-tab refusal naming `why`, without page info."""
    return set(result) == {"ok", "error"} and result["ok"] is False and result["error"].startswith("the surf tab is hidden") and why in result["error"]


def _jpeg(width, height):
    """The data URL the mock canvas encodes for an image of that size."""
    return "data:image/jpeg;base64," + base64.b64encode(f"jpeg {width}x{height}".encode()).decode()


ORIGIN = "https://example.org"
OLD = "https://example.org/old"
OLD_PAGE = {"url": OLD, "title": "Old", "status": None, "content_type": None}
SURF_TAB = {"7": {"url": OLD, "title": "Old", "windowId": 3}}
ASSASSIN_TAB = {"id": 9, "windowId": 3, "url": "http://127.0.0.1:8712/?token=abc&item=AI-ASSASSIN"}
STEPS = [{"type": "click", "x": 1, "y": 1}]
PAGE_ACTIONS = [{"action": "query", "origin": ORIGIN}, {"action": "screenshot", "origin": ORIGIN},
                {"action": "fill", "origin": ORIGIN, "selector": "#q", "value": "x"}, {"action": "mouse", "origin": ORIGIN, "steps": STEPS}]
EVERY = [{"action": "open", "url": "https://example.org/"}, {"action": "close"}, {"action": "status"}, *PAGE_ACTIONS]


@pytest.mark.syngate("BROWSER-EXTENSION-TAB", "replace")
def test_each_open_creates_the_surf_tab_anew_and_closes_the_one_before_every_other_request_acting_on_the_one_open():
    first, second = "https://example.org/a", "https://example.org/b"
    query = {"action": "query", "origin": ORIGIN, "selector": "h1"}
    run = _surf([{"action": "open", "url": first}, query, {"action": "open", "url": second}, query],
                inPage={"query": {"result": {"dom": "<h1>A</h1>", "matches": 1, "truncated": False}}}, changes={"1": {"waitMs": 20}, "3": {"waitMs": 20}})
    opened, queried, reopened, requeried = _plain(run["results"])
    assert opened == {"ok": True, "page": _pending(first), "placement": "tab"}
    assert queried == {"ok": True, "page": _page(first), "dom": "<h1>A</h1>", "matches": 1, "truncated": False}
    assert reopened == {"ok": True, "page": _pending(second), "placement": "tab"}
    assert requeried == {**queried, "page": _page(second)}
    assert [c for c in run["calls"] if c[0] != "scripting.executeScript"] == [
        ["tabs.create", {"url": first, "active": True}], ["tabs.create", {"url": second, "windowId": 2, "index": 0, "active": True}],
        ["tabs.remove", 100]]
    assert not [c for c in run["calls"] if c[0] == "tabs.update"]
    assert [c[1:] for c in run["calls"] if c[0] == "scripting.executeScript"] == [
        [{"tabId": tab}, "pageAction", "query", {"selector": "h1", "max_chars": None, "origin": ORIGIN}] for tab in (100, 101)]
    assert [frame["event"] for frame in run["frames"]] == ["load", "load"]
    assert run["tabId"] == 101 and run["listeners"][0] == run["listeners"][1]

    closed = _surf([{"action": "open", "url": first}], state={"tabId": 55})
    assert closed["results"][0]["placement"] == "tab" and closed["tabId"] == 100
    assert closed["calls"] == [["tabs.create", {"url": first, "active": True}]]


@pytest.mark.syngate("BROWSER-EXTENSION-TAB", "status")
def test_a_status_request_answers_the_page_info_of_the_surf_tab_alone():
    run = _surf([{"action": "status"}], tabs=SURF_TAB, state={"tabId": 7, "response": {"status": 404, "content_type": "text/plain"}})
    assert _plain(run["results"]) == [{"ok": True, "page": {"url": OLD, "title": "Old", "status": 404, "content_type": "text/plain"}}]
    assert run["calls"] == []

    unreported = _surf([{"action": "status"}], tabs=SURF_TAB, state={"tabId": 7})
    assert _plain(unreported["results"]) == [{"ok": True, "page": {"url": OLD, "title": "Old", "status": None, "content_type": None}}]


@pytest.mark.syngate("BROWSER-EXTENSION-TAB", "absent")
def test_while_no_surf_tab_is_open_every_request_but_open_is_refused():
    others = [{"action": "status"}, {"action": "query"}, {"action": "screenshot"}, {"action": "fill", "selector": "#q", "value": "x"},
              {"action": "mouse", "steps": [{"type": "click", "x": 1, "y": 1}]}]
    never = _surf(others)
    gone = _surf(others + [{"action": "open", "url": "https://example.org/"}], state={"tabId": 55})
    for run in (never, gone):
        assert _plain(run["results"][:5]) == [{"ok": False, "error": "no surf tab open"}] * 5
    assert never["calls"] == [] and never["checks"] == []
    assert gone["calls"] == [["tabs.create", {"url": "https://example.org/", "active": True}]] and gone["results"][5]["ok"] is True


@pytest.mark.syngate("BROWSER-EXTENSION-OPEN", "pending")
def test_an_open_answers_as_soon_as_the_new_tab_exists_with_its_pending_document_the_load_following_as_a_page_event():
    url, final = "https://example.org/go", "https://www.example.org/landed"
    run = _surf([{"action": "open", "url": url}], tabs=SURF_TAB, state={"tabId": 7, "page": OLD_PAGE, "response": {"status": 200, "content_type": HTML}},
                redirects={url: final}, timing={"start": 5, "load": 300}, status=203, afterMs=400)
    result = run["results"][0]
    assert result["ms"] < 100
    assert _plain([result]) == [{"ok": True, "page": _pending(url), "placement": "tab"}]
    assert run["calls"] == [["tabs.create", {"url": url, "windowId": 3, "index": 0, "active": True}], ["tabs.remove", 7]]
    assert run["frames"] == [{"type": "page", "event": "load", "page": _page(final, status=203)}]

    firefox = _surf([{"action": "open", "url": url}], tabs=SURF_TAB, state={"tabId": 7}, firefox=True)
    assert _plain(firefox["results"]) == [{"ok": True, "page": _pending(url), "placement": "tab"}]

    hung = _surf([{"action": "open", "url": url}, {"action": "status"}], hang=True)
    opened, status = _plain(hung["results"])
    assert opened == {"ok": True, "page": _pending(url), "placement": "tab"} and status == {"ok": True, "page": _pending(url)}
    assert hung["frames"] == []


@pytest.mark.syngate("BROWSER-EXTENSION-OPEN", "scheme")
def test_an_open_of_any_scheme_but_http_and_https_is_refused():
    refused = ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,hi", "chrome://settings/", "ftp://example.org/"]
    run = _surf([{"action": "open", "url": url} for url in refused] + [{"action": "open", "url": "http://example.org/"}])
    for url, result in zip(refused, run["results"]):
        assert result["ok"] is False and url.split(":")[0] + ":" in result["error"]
    assert run["results"][-1]["ok"] is True
    assert run["calls"] == [["tabs.create", {"url": "http://example.org/", "active": True}]]


@pytest.mark.syngate("BROWSER-EXTENSION-OPEN", "place")
def test_an_open_puts_the_new_surf_tab_in_the_place_of_the_previous_one_before_closing_it_and_places_anew_the_successor_of_a_split_one():
    url = "https://example.org/next"
    tiled = _surf([{"action": "open", "url": url}], tabs={"7": {"url": OLD, "windowId": 3, "index": 2}}, state={"tabId": 7, "placement": "tiled"})
    assert _plain(tiled["results"]) == [{"ok": True, "page": _pending(url), "placement": "tiled"}]
    assert tiled["calls"] == [["tabs.create", {"url": url, "windowId": 3, "index": 2, "active": True}], ["tabs.remove", 7]]
    assert tiled["tabId"] == 100

    in_split = {"7": {"url": OLD, "windowId": 3, "index": 1, "active": False, "splitViewId": 4}}
    split = _surf([{"action": "open", "url": url}], tabs=in_split, state={"tabId": 7, "placement": "split"}, split=True, query=[ASSASSIN_TAB])
    assert _plain(split["results"]) == [{"ok": True, "page": _pending(url), "placement": "split"}]
    assert split["calls"] == [["tabs.remove", 7], ["tabs.create", {"url": url, "splitWithTabId": 9}]]
    assert split["tabId"] == 100 and [frame["event"] for frame in split["frames"]] == ["load"]

    alone = _surf([{"action": "open", "url": url}], tabs=in_split, state={"tabId": 7, "placement": "split"}, split=True)
    assert _plain(alone["results"]) == [{"ok": True, "page": _pending(url), "placement": "tab"}]
    assert alone["calls"] == [["tabs.remove", 7], ["tabs.create", {"url": url, "active": True, "windowId": 3}]]


@pytest.mark.syngate("BROWSER-EXTENSION-CLOSE")
def test_a_close_closes_the_surf_tab_its_closing_reported_as_a_page_event_and_the_next_open_creates_a_fresh_one():
    url = "https://example.org/fresh"
    run = _surf([{"action": "status"}, {"action": "close"}, {"action": "status"}, {"action": "close"}, {"action": "open", "url": url}],
                tabs=SURF_TAB, state={"tabId": 7, "placement": "tiled"})
    status, closed, after, again, opened = _plain(run["results"])
    assert status == {"ok": True, "page": OLD_PAGE} and closed == {"ok": True}
    assert after == again == {"ok": False, "error": "no surf tab open"}
    assert opened == {"ok": True, "page": _pending(url), "placement": "tab"}
    assert run["calls"] == [["tabs.remove", 7], ["tabs.create", {"url": url, "active": True}]]
    assert run["frames"] == [{"type": "page", "event": "closed", "page": OLD_PAGE}, {"type": "page", "event": "load", "page": _page(url)}]
    assert run["tabId"] == 100


@pytest.mark.syngate("BROWSER-EXTENSION-HIDDEN", "tab")
def test_every_request_is_refused_without_page_info_while_the_surf_tab_is_minimized_hidden_or_behind_another_tab_until_shown_or_closed():
    for tab, windows, why in [({}, {"3": {"state": "minimized"}}, "minimized"), ({"hidden": True}, {}, "hides"),
                              ({"active": False}, {}, "another tab"), ({"active": False, "splitViewId": -1}, {}, "another tab")]:
        run = _surf(EVERY, tabs={"7": {"url": OLD, "title": "Old", "windowId": 3, **tab}}, windows=windows, state={"tabId": 7})
        assert all(_hidden(result, why) for result in _plain(run["results"])), run["results"]
        assert run["calls"] == [] and run["tabId"] == 7 and run["frames"] == []

    behind = {"7": {"url": OLD, "title": "Old", "windowId": 3, "active": False}}
    shown = _surf([{"action": "status"}, {"action": "status"}], tabs=behind, state={"tabId": 7}, changes={"1": {"tabs": {"7": {"active": True}}}})
    refused, answered = _plain(shown["results"])
    assert _hidden(refused, "another tab") and answered == {"ok": True, "page": OLD_PAGE}

    restored = _surf([{"action": "status"}, {"action": "status"}], tabs=SURF_TAB, windows={"3": {"state": "minimized"}}, state={"tabId": 7},
                     changes={"1": {"windows": {"3": {"state": "maximized"}}}})
    refused, answered = _plain(restored["results"])
    assert _hidden(refused, "minimized") and answered == {"ok": True, "page": OLD_PAGE}

    closed = _surf([{"action": "status"}, {"action": "open", "url": "https://example.org/"}], tabs=behind, state={"tabId": 7},
                   changes={"1": {"close": [7]}})
    refused, opened = _plain(closed["results"])
    assert _hidden(refused, "another tab") and opened["ok"] is True and closed["tabId"] == 100
    assert closed["calls"] == [["tabs.create", {"url": "https://example.org/", "active": True}]]

    split = _surf([{"action": "status"}], tabs={"7": {"url": OLD, "title": "Old", "windowId": 3, "active": False, "splitViewId": 4}}, state={"tabId": 7})
    assert _plain(split["results"]) == [{"ok": True, "page": OLD_PAGE}] and split["calls"] == []


@pytest.mark.syngate("BROWSER-EXTENSION-HIDDEN", "page")
def test_a_page_action_is_refused_while_its_page_reports_itself_hidden_the_page_asked_in_the_script_that_plays_it():
    unseen = {"result": {"hidden": "its page is not visible"}}
    run = _surf(PAGE_ACTIONS, tabs=SURF_TAB, state={"tabId": 7}, inPage={"query": unseen, "mask true": unseen, "fill": unseen, "mouse": unseen})
    assert all(_hidden(result, "page") for result in _plain(run["results"])), run["results"]
    played = [c[3] for c in run["calls"] if c[0] == "scripting.executeScript"]
    assert played == ["query", "mask", "mask", "fill", "mouse"] and not [c for c in run["calls"] if c[0] == "tabs.captureVisibleTab"]

    by_tab = _surf([{"action": "status"}, {"action": "close"}, {"action": "open", "url": "https://example.org/"}], tabs=SURF_TAB, state={"tabId": 7})
    assert [result["ok"] for result in by_tab["results"]] == [True, True, True]
    assert not [c for c in by_tab["calls"] if c[0] == "scripting.executeScript"]

    for action, options in [("query", {"selector": "h1"}), ("fill", {"selector": "#q", "value": "x"}), ("mouse", {"steps": STEPS}), ("mask", {"on": True})]:
        for origin in (ORIGIN, "https://other.example"):
            assert _in_page(action, {**options, "origin": ORIGIN}, "hidden", origin) == {"hidden": "its page is not visible"}, action


@pytest.mark.syngate("BROWSER-EXTENSION-ORIGIN", "request")
def test_a_page_action_carries_its_origin_into_the_page_and_answers_the_pages_refusal_with_the_page_info():
    wrong = "the surf tab's page is on https://example.org, not https://example.com: check it and repeat the call with its origin"
    elsewhere = [{**action, "origin": "https://example.com"} for action in PAGE_ACTIONS]
    refusal = {"result": {"error": wrong}}
    run = _surf(elsewhere + [{"action": action} for action in ("query", "screenshot", "fill", "mouse")], tabs=SURF_TAB, state={"tabId": 7},
                inPage={"query": refusal, "mask true": refusal, "fill": refusal, "mouse": refusal})
    refused, unnamed = _plain(run["results"][:4]), _plain(run["results"][4:])
    assert refused == [{"ok": False, "error": wrong, "page": OLD_PAGE}] * 4
    assert all(result["ok"] is False and "origin" in result["error"] and "page" not in result for result in unnamed)
    injected = [(c[3], c[4]) for c in run["calls"] if c[0] == "scripting.executeScript"]
    assert injected == [("query", {"selector": None, "max_chars": None, "origin": "https://example.com"}), ("mask", {"on": True, "origin": "https://example.com"}),
                        ("mask", {"on": False}), ("fill", {"selector": "#q", "value": "x", "origin": "https://example.com"}),
                        ("mouse", {"steps": STEPS, "origin": "https://example.com"})]
    assert not [c for c in run["calls"] if c[0] == "tabs.captureVisibleTab"]


@pytest.mark.syngate("BROWSER-EXTENSION-SCREENSHOT", "capture")
def test_a_screenshot_answers_the_visible_part_of_the_activated_surf_tab_as_a_jpeg_of_its_css_pixels_with_viewport_and_scales():
    masked = {"viewport": {"width": 1280, "height": 720}, "scale": 2, "masked": 1}
    run = _surf([{"action": "screenshot", "origin": ORIGIN}], tabs=SURF_TAB, state={"tabId": 7}, inPage={"mask true": {"result": masked}}, captured=[2560, 1440])
    assert _plain(run["results"]) == [{"ok": True, "page": OLD_PAGE, "image": _jpeg(1280, 720), "viewport": {"width": 1280, "height": 720},
                                       "scale": 2, "image_scale": 1}]
    assert run["calls"] == [
        ["tabs.update", 7, {"active": True}],
        ["scripting.executeScript", {"tabId": 7, "allFrames": True}, "pageAction", "mask", {"on": True, "origin": ORIGIN}],
        ["scripting.executeScript", {"tabId": 7}, "pageAction", "paint", {"origin": ORIGIN}],
        ["tabs.captureVisibleTab", 3, {"format": "png"}],
        ["scripting.executeScript", {"tabId": 7, "allFrames": True}, "pageAction", "mask", {"on": False}],
        ["createImageBitmap", "image/png", "capture"],
        ["drawImage", "2d", 0, 0, 1280, 720],
        ["bitmap.close"],
        ["convertToBlob", {"type": "image/jpeg", "quality": 0.8}],
    ]


@pytest.mark.syngate("BROWSER-EXTENSION-SCREENSHOT", "fit")
def test_a_screenshot_is_scaled_below_the_css_pixels_to_fit_the_longest_edge_and_the_area_asked_never_above_them():
    masked = {"viewport": {"width": 1280, "height": 720}, "scale": 2, "masked": 0}
    asked = [{"max_edge": 640}, {"max_pixels": 115_200}, {"max_edge": 1000, "max_pixels": 400_000}, {"max_edge": 4000, "max_pixels": 10**8}]
    run = _surf([{"action": "screenshot", "origin": ORIGIN, **limits} for limits in asked], tabs=SURF_TAB, state={"tabId": 7},
                inPage={"mask true": {"result": masked}})
    sizes = [tuple(c[4:]) for c in run["calls"] if c[0] == "drawImage"]
    assert sizes == [(640, 360), (452, 254), (843, 474), (1280, 720)]
    results = _plain(run["results"])
    assert [result["image"] for result in results] == [_jpeg(*size) for size in sizes]
    assert [result["image_scale"] for result in results] == pytest.approx([0.5, 0.125 ** 0.5, (400_000 / 921_600) ** 0.5, 1])
    for (width, height), limits, result in zip(sizes, asked, results):
        assert width * height <= limits.get("max_pixels", width * height) and max(width, height) <= limits.get("max_edge", 1280)
        assert result["viewport"] == {"width": 1280, "height": 720} and result["scale"] == 2


@pytest.mark.syngate("BROWSER-EXTENSION-MOUSE", "played")
def test_a_mouse_request_answers_once_played_with_the_page_as_it_then_is_a_navigation_it_started_following_as_a_page_event():
    item = "https://example.org/item"
    steps = [{"type": "click", "selector": "a"}]
    run = _surf([{"action": "mouse", "origin": ORIGIN, "steps": steps}], tabs=SURF_TAB, state={"tabId": 7},
                inPage={"mouse": {"navigate": {"url": item, "start": 5, "load": 50}}}, afterMs=150)
    result = run["results"][0]
    assert result["ms"] < 50 and _plain([result]) == [{"ok": True, "page": OLD_PAGE}]
    assert run["calls"] == [["scripting.executeScript", {"tabId": 7}, "pageAction", "mouse", {"steps": steps, "origin": ORIGIN}]]
    assert run["frames"] == [{"type": "page", "event": "load", "page": _page(item)}]


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "gone")
def test_a_page_action_answers_when_its_document_goes_away_under_it():
    item = "https://example.org/item"
    moved = _surf([{"action": "mouse", "origin": ORIGIN, "steps": STEPS}], tabs=SURF_TAB, state={"tabId": 7},
                  inPage={"mouse": {"hang": True, "navigate": {"url": item, "start": 20, "load": 10}}})
    result = moved["results"][0]
    assert 25 <= result["ms"] < 1000 and result["ok"] is False and "went away" in result["error"] and "committed" in result["error"]
    assert result["page"]["url"] == item and moved["listeners"][0] == moved["listeners"][1]

    closed = _surf([{"action": "query", "origin": ORIGIN}], tabs=SURF_TAB, state={"tabId": 7}, inPage={"query": {"hang": True, "close": 30}})
    result = closed["results"][0]
    assert 25 <= result["ms"] < 1000 and _plain([result]) == [{"ok": False, "error": result["error"]}] and "closed" in result["error"]
    assert closed["tabId"] is None and closed["listeners"][0] == closed["listeners"][1]

    shot = _surf([{"action": "screenshot", "origin": ORIGIN}], tabs=SURF_TAB, state={"tabId": 7},
                 inPage={"mask true": {"hang": True, "close": 30}, "mask false": {"hang": True}})
    assert shot["results"][0]["ok"] is False and "closed" in shot["results"][0]["error"]


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "untimed")
def test_no_request_waits_on_a_page_load_or_a_set_time():
    for name in ("surf.js", "events.js", "background.js", "placement.js", "bridge.js"):
        source = (EXTENSION / name).read_text(encoding="utf-8")
        assert "setTimeout" not in source and not re.search(r"TIMEOUT|SETTLE", source), name
    assert (EXTENSION / "bridge.js").read_text(encoding="utf-8").count("setInterval(") == 1

    url = "https://example.org/never"
    run = _surf([{"action": "open", "url": url}, {"action": "status"}, *PAGE_ACTIONS, {"action": "close"}], hang=True,
                inPage={"mask true": {"result": {"viewport": {"width": 1280, "height": 720}, "scale": 1}}})
    assert [result["ok"] for result in run["results"]] == [True] * 7
    assert all(result["ms"] < 100 for result in run["results"]), run["results"]
