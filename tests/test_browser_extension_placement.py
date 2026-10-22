# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/placement.js`, and `surf.js` opening through it, run by node against a mock `browser` recording its calls --
[BROWSER-EXTENSION-PLACEMENT], [BROWSER-EXTENSION-WINDOW-LABEL]."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLACEMENT = ROOT / "websurf-extension" / "placement.js"
SURF = ROOT / "websurf-extension" / "surf.js"
HARNESS = "http://127.0.0.1:8713/"
PAGE = "https://example.org/page"
DRIVER = """
import { placeSurfTab } from %(placement)s;
import { surf } from %(surf)s;
const cfg = JSON.parse(process.argv[1]);
const calls = [];
const record = (name, impl) => async (...args) => { calls.push([name, ...args]); return impl(...args); };
const tabs = {
  query: record('tabs.query', () => cfg.tabs),
  create: record('tabs.create', (props) => {
    if (props.splitWithTabId !== undefined && cfg.refuseSplit) throw new Error('split refused');
    return { id: 99, url: props.url };
  }),
  get: async (id) => ({ id, windowId: 7, url: cfg.url, title: '' }),
};
if (cfg.split) tabs.createSplit = record('tabs.createSplit', () => ({}));
const windows = {
  get: record('windows.get', (id) => ({ id, ...cfg.bounds })),
  update: record('windows.update', (id, props) => ({ id, ...props })),
  create: record('windows.create', (props) => ({ id: 7, ...props, tabs: [{ id: 99 }] })),
};
// Firefox tells its runtime.getBrowserInfo, Chrome has none
const api = cfg.firefox ? { tabs, windows, runtime: { getBrowserInfo: async () => ({ name: 'Firefox' }) } } : { tabs, windows };
// placed for the session of the harness at that origin, or opened by a surf request of that session
const origin = new URL(cfg.harness).origin;
const result = cfg.request
  ? await surf(api, cfg.request, { origin }, { tabId: null, placement: null, response: null, page: null })
  : await placeSurfTab(api, cfg.url, origin, cfg.window ?? undefined, ...(cfg.tiling ? [cfg.tiling] : []));
console.log(JSON.stringify({ result, calls }));
"""


def _place(tabs, split=False, refuse_split=False, bounds=None, window=None, tiling=None, firefox=False, harness=HARNESS, request=None):
    """Return the placement result and the recorded browser calls of one `placeSurfTab` run under node -- `window` being the previous
    surf tab's, `tiling` the harness's method, `firefox` a browser taking `titlePreface` -- or of the surf `request` run by `surf.js`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"tabs": tabs, "split": split, "refuseSplit": refuse_split, "bounds": bounds, "url": PAGE, "harness": harness, "window": window,
           "tiling": tiling, "firefox": firefox, "request": request}
    script = DRIVER % {"placement": json.dumps(PLACEMENT.as_uri()), "surf": json.dumps(SURF.as_uri())}
    out = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(cfg)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


ASSASSIN_TAB = {"id": 3, "windowId": 5, "url": HARNESS + "?token=abc&item=AI-ASSASSIN"}
OTHER_TAB = {"id": 4, "windowId": 6, "url": "https://example.com/"}
LABEL = "WebSurf 8713 · "
SHOWN = {**ASSASSIN_TAB, "active": True, "title": "AI-ASSASSIN · AI Assassin"}


@pytest.mark.syngate("BROWSER-EXTENSION-PLACEMENT", "session")
def test_the_page_opens_beside_the_assassin_tab_of_its_own_session_never_beside_another_servers():
    other = {"id": 2, "windowId": 4, "url": "http://127.0.0.1:8712/?token=abc"}
    run = _place([other, ASSASSIN_TAB], split=True)
    assert [c for c in run["calls"] if c[0] == "tabs.create"] == [["tabs.create", {"url": PAGE, "splitWithTabId": 3}]]
    for alone in (other, {"id": 5, "windowId": 4, "url": HARNESS + "?item=AI-ASSASSIN"}, {"id": 6, "windowId": 4, "url": HARNESS + "chat?token=abc"}):
        run = _place([alone], split=True)  # another server's tab, or one of this origin that is no Assassin tab
        assert run["result"]["placement"] == "tab" and [c for c in run["calls"] if c[0] == "tabs.create"] == [["tabs.create", {"url": PAGE, "active": True}]]


@pytest.mark.syngate("BROWSER-EXTENSION-PLACEMENT", "split")
def test_the_page_opens_split_with_the_assassin_tab_where_the_browser_offers_split_view():
    run = _place([OTHER_TAB, ASSASSIN_TAB], split=True)
    assert run["result"]["placement"] == "split"
    creates = [c for c in run["calls"] if c[0] == "tabs.create"]
    assert creates == [["tabs.create", {"url": PAGE, "splitWithTabId": 3}]]
    assert not [c for c in run["calls"] if c[0].startswith("windows.")]


@pytest.mark.syngate("BROWSER-EXTENSION-PLACEMENT", "tiled")
def test_the_page_opens_in_a_window_tiled_against_the_assassin_window_along_its_longer_side():
    landscape = _place([ASSASSIN_TAB], bounds={"left": 100, "top": 50, "width": 1600, "height": 900})
    assert landscape["result"]["placement"] == "tiled"
    assert ["windows.update", 5, {"left": 100, "top": 50, "width": 800, "height": 900}] in landscape["calls"]
    assert ["windows.create", {"url": PAGE, "left": 900, "top": 50, "width": 800, "height": 900}] in landscape["calls"]
    assert not [c for c in landscape["calls"] if c[0] == "tabs.create"]

    portrait = _place([ASSASSIN_TAB], bounds={"left": 0, "top": 0, "width": 900, "height": 1601})
    assert portrait["result"]["placement"] == "tiled"
    assert ["windows.update", 5, {"left": 0, "top": 0, "width": 900, "height": 800}] in portrait["calls"]
    assert ["windows.create", {"url": PAGE, "left": 0, "top": 800, "width": 900, "height": 801}] in portrait["calls"]

    refused = _place([ASSASSIN_TAB], split=True, refuse_split=True, bounds={"left": 0, "top": 0, "width": 1000, "height": 1000})
    assert refused["result"]["placement"] == "tiled"
    assert ["windows.create", {"url": PAGE, "left": 500, "top": 0, "width": 500, "height": 1000}] in refused["calls"]


@pytest.mark.syngate("BROWSER-EXTENSION-PLACEMENT", "tab")
def test_the_page_opens_as_the_active_tab_of_the_current_window_or_of_the_previous_surf_tabs_when_no_assassin_tab_is_open():
    run = _place([OTHER_TAB], split=True)
    assert run["result"]["placement"] == "tab"
    assert [c for c in run["calls"] if c[0] != "tabs.query"] == [["tabs.create", {"url": PAGE, "active": True}]]

    replacing = _place([OTHER_TAB], split=True, window=8)
    assert replacing["result"]["placement"] == "tab"
    assert [c for c in replacing["calls"] if c[0] != "tabs.query"] == [["tabs.create", {"url": PAGE, "active": True, "windowId": 8}]]


@pytest.mark.syngate("BROWSER-EXTENSION-PLACEMENT", "compositor")
def test_under_kwin_and_none_the_assassin_window_is_left_as_it_is_and_a_kwin_answer_names_the_titles_finding_both_windows():
    bounds = {"left": 0, "top": 0, "width": 1600, "height": 900}
    kwin = _place([OTHER_TAB, SHOWN], bounds=bounds, tiling="kwin", firefox=True)
    assert kwin["result"] == {"placement": "tiled", "window": {"id": 7, "url": PAGE, "titlePreface": LABEL, "tabs": [{"id": 99}]},
                              "tile": {"surf": LABEL, "assassin": "AI-ASSASSIN · AI Assassin"}}
    assert [c for c in kwin["calls"] if c[0] != "tabs.query"] == [["windows.create", {"url": PAGE, "titlePreface": LABEL}]]  # no get, no update

    behind = _place([{**SHOWN, "active": False}], bounds=bounds, tiling="kwin", firefox=True)  # its title is no window's caption then
    assert behind["result"]["tile"] == {"surf": LABEL, "assassin": None}

    none = _place([SHOWN], bounds=bounds, tiling="none", firefox=True)
    assert none["result"]["placement"] == "window" and "tile" not in none["result"]
    assert [c for c in none["calls"] if c[0] != "tabs.query"] == [["windows.create", {"url": PAGE, "titlePreface": LABEL}]]

    chrome = _place([SHOWN], bounds=bounds, tiling="kwin")  # an unlabelled window no compositor script can find
    assert chrome["result"]["placement"] == "tiled" and "tile" not in chrome["result"]
    assert [c for c in chrome["calls"] if c[0] != "tabs.query"] == [["windows.create", {"url": PAGE}]]

    split = _place([SHOWN], split=True, tiling="kwin", firefox=True)  # a native split needs no tiling
    assert split["result"]["placement"] == "split" and not [c for c in split["calls"] if c[0].startswith("windows.")]

    opened = _place([SHOWN], bounds=bounds, firefox=True, request={"action": "open", "url": PAGE, "tiling": "kwin"})
    assert opened["result"] == {"ok": True, "page": {"url": PAGE, "title": "", "status": None, "content_type": None}, "placement": "tiled",
                                "tile": {"surf": LABEL, "assassin": "AI-ASSASSIN · AI Assassin"}}
    plain = _place([SHOWN], bounds=bounds, firefox=True, request={"action": "open", "url": PAGE})  # no method sent: the browser tiles
    assert plain["result"]["placement"] == "tiled" and "tile" not in plain["result"]
    assert ["windows.update", 5, {"left": 0, "top": 0, "width": 800, "height": 900}] in plain["calls"]


@pytest.mark.syngate("BROWSER-EXTENSION-WINDOW-LABEL")
def test_every_surf_window_is_labelled_with_the_port_of_its_sessions_harness_where_the_browser_takes_a_title_preface():
    bounds = {"left": 0, "top": 0, "width": 1600, "height": 900}
    other = "http://127.0.0.1:8799/"
    firefox = _place([{**SHOWN, "url": other + "?token=abc"}], bounds=bounds, firefox=True, harness=other)
    assert ["windows.create", {"url": PAGE, "titlePreface": "WebSurf 8799 · ", "left": 800, "top": 0, "width": 800, "height": 900}] in firefox["calls"]
    for tiling in ("kwin", "none"):
        assert _place([SHOWN], bounds=bounds, firefox=True, tiling=tiling)["calls"][-1] == ["windows.create", {"url": PAGE, "titlePreface": LABEL}]

    chrome = _place([SHOWN], bounds=bounds)
    assert ["windows.create", {"url": PAGE, "left": 800, "top": 0, "width": 800, "height": 900}] in chrome["calls"]
    assert not any("titlePreface" in c[1] for c in chrome["calls"] if c[0] == "windows.create")
