# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/events.js` run by node against a mock `browser` firing navigation, response and tab events -- [BROWSER-EXTENSION-EVENTS]."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "websurf-extension" / "events.js"
DRIVER = """
import { watchSurfTab } from %s;
const cfg = JSON.parse(process.argv[1]);
const registered = {}, tabs = new Map(), frames = [];
const event = (name) => {
  const listeners = new Set();
  return { addListener: (l, ...extra) => { listeners.add(l); registered[name] = extra; }, removeListener: (l) => listeners.delete(l),
           fire: (...args) => [...listeners].forEach((l) => l(...args)) };
};
const api = {
  tabs: { get: async (id) => { if (!tabs.has(id)) throw new Error(`no tab ${id}`); return { ...tabs.get(id) }; }, onRemoved: event('tabs.onRemoved') },
  webNavigation: {},
  webRequest: { onCompleted: event('webRequest.onCompleted') },
};
for (const name of ['onBeforeNavigate', 'onCompleted', 'onErrorOccurred', 'onHistoryStateUpdated', 'onReferenceFragmentUpdated']) {
  api.webNavigation[name] = event(`webNavigation.${name}`);
}
const state = { tabId: 7, response: null, page: null };
watchSurfTab(api, state, (frame) => frames.push(frame));
for (const [name, details] of cfg.fires) {
  if (name === 'tab') tabs.set(details.id, details);
  else if (name === 'tabs.onRemoved') { tabs.delete(details); api.tabs.onRemoved.fire(details, { windowId: 1, isWindowClosing: false }); }
  else { const [area, kind] = name.split('.'); api[area][kind].fire(details); }
  await new Promise((resolve) => setTimeout(resolve, 2));
}
await new Promise((resolve) => setTimeout(resolve, 20));
console.log(JSON.stringify({ frames, tabId: state.tabId, registered }));
"""


def _events(fires):
    """Return the page frames emitted, the surf tab id left and the listener filters registered when `fires` reach events.js under node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "--input-type=module", "-e", DRIVER % json.dumps(EVENTS.as_uri()), json.dumps({"fires": list(fires)})],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


A, B = "https://example.org/a", "https://example.org/b"


def _nav(kind, url, tab=7, frame=0):
    return (f"webNavigation.{kind}", {"tabId": tab, "frameId": frame, "url": url})


def _response(url, status, tab=7, content_type="text/html"):
    return ("webRequest.onCompleted", {"tabId": tab, "frameId": 0, "type": "main_frame", "url": url, "statusCode": status,
                                       "responseHeaders": [{"name": "server", "value": "x"}, {"name": "content-type", "value": content_type}]})


def _load(url, status=None, tab=7, title=None):
    """The events of a top-level document of `url` loading in `tab`, with a main-frame response of `status` unless None."""
    return [("tab", {"id": tab, "url": url, "title": title or url.rsplit("/", 1)[-1].upper()}), _nav("onBeforeNavigate", url, tab),
            *([_response(url, status, tab)] if status is not None else []), _nav("onCompleted", url, tab)]


def _info(url, title, status, content_type="text/html"):
    return {"url": url, "title": title, "status": status, "content_type": content_type if status is not None else None}


@pytest.mark.syngate("BROWSER-EXTENSION-EVENTS", "load")
def test_each_top_level_document_loaded_in_the_surf_tab_is_reported_with_its_main_frame_response():
    run = _events([*_load(A, 404, title="Missing"), *_load(B)])
    assert run["frames"] == [{"type": "page", "event": "load", "page": _info(A, "Missing", 404)},
                             {"type": "page", "event": "load", "page": _info(B, "B", None)}]
    assert run["registered"]["webRequest.onCompleted"] == [{"urls": ["<all_urls>"], "types": ["main_frame"]}, ["responseHeaders"]]


@pytest.mark.syngate("BROWSER-EXTENSION-EVENTS", "history")
def test_each_url_change_within_the_document_of_the_surf_tab_is_reported_as_history():
    run = _events([*_load(A, 200), ("tab", {"id": 7, "url": A + "/2", "title": "Second"}), _nav("onHistoryStateUpdated", A + "/2"),
                   _nav("onReferenceFragmentUpdated", A + "/2#reviews")])
    assert run["frames"] == [{"type": "page", "event": "load", "page": _info(A, "A", 200)},
                             {"type": "page", "event": "history", "page": _info(A + "/2", "Second", 200)},
                             {"type": "page", "event": "history", "page": _info(A + "/2#reviews", "Second", 200)}]


@pytest.mark.syngate("BROWSER-EXTENSION-EVENTS", "closed")
def test_the_closing_of_the_surf_tab_is_reported_with_its_last_known_page_info():
    run = _events([*_load(A, 200), ("tabs.onRemoved", 7), *_load(B, 200)])
    assert run["frames"] == [{"type": "page", "event": "load", "page": _info(A, "A", 200)},
                             {"type": "page", "event": "closed", "page": _info(A, "A", 200)}]
    assert run["tabId"] is None


@pytest.mark.syngate("BROWSER-EXTENSION-EVENTS", "failed")
def test_each_top_level_navigation_of_the_surf_tab_that_failed_is_reported_with_the_browsers_error():
    gone = "https://unreachable.example/"
    error = lambda url, why, tab=7, frame=0: ("webNavigation.onErrorOccurred", {"tabId": tab, "frameId": frame, "url": url, "error": why})
    run = _events([*_load(A, 200), _nav("onBeforeNavigate", gone), error(gone, "net::ERR_NAME_NOT_RESOLVED"),
                   error(A + "/ad", "net::ERR_BLOCKED_BY_CLIENT", frame=2), error(B, "net::ERR_ABORTED", tab=8), *_load(B, 200)])
    assert run["frames"] == [{"type": "page", "event": "load", "page": _info(A, "A", 200)},
                             {"type": "page", "event": "failed", "page": _info(gone, "A", None), "error": "net::ERR_NAME_NOT_RESOLVED"},
                             {"type": "page", "event": "load", "page": _info(B, "B", 200)}]


@pytest.mark.syngate("BROWSER-EXTENSION-EVENTS", "other")
def test_no_other_tab_and_no_subframe_is_ever_reported():
    run = _events([*_load(B, 500, tab=8), _nav("onHistoryStateUpdated", B + "#x", tab=8), ("tabs.onRemoved", 8),
                   ("tab", {"id": 7, "url": A, "title": "A"}), _nav("onCompleted", A + "/frame", frame=3),
                   _nav("onHistoryStateUpdated", A + "/frame#x", frame=3), _nav("onBeforeNavigate", A), _response(B, 500, tab=8),
                   _nav("onCompleted", A)])
    assert run["frames"] == [{"type": "page", "event": "load", "page": _info(A, "A", None)}]
    assert run["tabId"] == 7
