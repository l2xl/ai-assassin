# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/background.js` run by node against a mock browser -- its tab strip, storage, alarms and WebSockets -- finding the
AI Assassin sessions from the URLs of their tabs and serving each over a bridge and with a surf tab of its own --
[BROWSER-EXTENSION-SESSION], [BROWSER-EXTENSION-ISOLATION]."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "websurf-extension"
DRIVER = """
const cfg = JSON.parse(process.argv[1]);
const log = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const event = () => {
  const listeners = new Set();
  return { addListener: (l) => listeners.add(l), removeListener: (l) => listeners.delete(l), fire: (...args) => [...listeners].forEach((l) => l(...args)) };
};
const shown = { windowId: 1, index: 0, active: true, hidden: false, splitViewId: -1, title: '' };
const tabs = new Map((cfg.tabs || []).map((tab) => [tab.id, { ...shown, ...tab }]));
let nextId = 100;
const updated = event(), removed = event(), alarm = event(), clicked = event(), responses = event(), nav = {};
for (const name of ['onBeforeNavigate', 'onCommitted', 'onCompleted', 'onErrorOccurred', 'onHistoryStateUpdated', 'onReferenceFragmentUpdated']) nav[name] = event();
// a storage area: what it holds when the background starts, and what it holds at the end
const area = (initial) => {
  const data = structuredClone(initial || {});
  return { data, get: async (defaults) => ({ ...defaults, ...structuredClone(data) }), set: async (items) => { Object.assign(data, structuredClone(items)); } };
};
const storage = { local: area(cfg.local), ...(cfg.noSession ? {} : { session: area(cfg.session) }), onChanged: event() };
globalThis.chrome = {
  storage,
  action: { setBadgeText: ({ text }) => log.push(['badge', text]), onClicked: clicked },
  runtime: { onInstalled: event(), onStartup: event(), openOptionsPage: () => log.push(['options']) },
  alarms: { onAlarm: alarm, create: (name, info) => log.push(['alarm', name, info]) },
  tabs: {
    query: async () => [...tabs.values()].map((tab) => ({ ...tab })),
    get: async (id) => { if (!tabs.has(id)) throw new Error(`no tab ${id}`); return { ...tabs.get(id) }; },
    create: async (props) => {
      log.push(['create', props]);
      const tab = { ...shown, id: nextId++, windowId: props.windowId ?? 1, index: props.index ?? 0, splitViewId: props.splitWithTabId === undefined ? -1 : 1,
                    url: '', pendingUrl: props.url };
      tabs.set(tab.id, tab);
      return { ...tab };
    },
    update: async (id, props) => { log.push(['update', id, props]); return { ...tabs.get(id) }; },
    remove: async (id) => { log.push(['remove', id]); if (!tabs.has(id)) throw new Error(`no tab ${id}`); tabs.delete(id); removed.fire(id, {}); },
    onUpdated: updated,
    onRemoved: removed,
    ...(cfg.split ? { createSplit: async () => ({}) } : {}),
  },
  windows: { get: async (id) => ({ id, state: 'normal', left: 0, top: 0, width: 1600, height: 900 }) },
  webNavigation: nav,
  webRequest: { onCompleted: responses },
  scripting: { executeScript: async ({ target, args }) => { log.push(['inject', target.tabId, args[0]]); return [{ frameId: 0, result: {} }]; } },
};
const sockets = [];
globalThis.WebSocket = class {
  constructor(url) { Object.assign(this, { url, readyState: 0, sent: [], closed: false }); sockets.push(this); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { if (this.closed) return; Object.assign(this, { closed: true, readyState: 3 }); if (this.onclose) this.onclose({ code: 1000 }); }
};
// the newest socket to the harness of `origin`
const socketOf = (origin) => [...sockets].reverse().find((socket) => socket.url === `ws://${new URL(origin).host}/websurf`);
// a top-level document of `url` loading in tab `id`, as the browser tells it
const load = (id, url) => {
  nav.onBeforeNavigate.fire({ tabId: id, frameId: 0, url });
  nav.onCommitted.fire({ tabId: id, frameId: 0, url });
  responses.fire({ tabId: id, frameId: 0, type: 'main_frame', url, statusCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'text/html' }] });
  Object.assign(tabs.get(id), { url, title: `Title of ${url}`, pendingUrl: undefined });
  updated.fire(id, { url }, { ...tabs.get(id) });
  nav.onCompleted.fire({ tabId: id, frameId: 0, url });
};
await import(cfg.background);
await sleep(20);
for (const [kind, ...args] of cfg.steps || []) {
  if (kind === 'tab') {
    const [tab] = args;
    tabs.set(tab.id, { ...shown, ...tabs.get(tab.id), ...tab });
    updated.fire(tab.id, { url: tab.url }, { ...tabs.get(tab.id) });
  } else if (kind === 'close') {
    tabs.delete(args[0]);
    removed.fire(args[0], {});
  } else if (kind === 'load') {
    load(...args);
  } else if (kind === 'welcome') {
    const socket = socketOf(args[0]);
    socket.readyState = 1;
    socket.onopen();
    await socket.onmessage({ data: JSON.stringify({ type: 'welcome' }) });
  } else if (kind === 'surf') {
    await socketOf(args[0]).onmessage({ data: JSON.stringify({ type: 'surf', ...args[1] }) });
  } else if (kind === 'drop') {
    const socket = socketOf(args[0]);
    socket.readyState = 3;
    socket.onclose({ code: 1006 });
  } else if (kind === 'alarm') {
    alarm.fire({ name: 'websurf-bridge' });
  } else if (kind === 'click') {
    clicked.fire({});
  }
  await sleep(10);
}
await sleep(20);
console.log(JSON.stringify({ sockets: sockets.map(({ url, sent, closed }) => ({ url, sent, closed })), log, tabs: [...tabs.keys()],
                             stored: { local: storage.local.data, session: storage.session ? storage.session.data : null } }));
process.exit(0);
"""


def _run(steps=(), tabs=(), session=None, local=None, **cfg):
    """Return the sockets opened -- each its URL, the frames sent and whether closed --, the log of badge texts, tab calls and injections,
    the tab ids left and what storage holds at the end of `background.js` started on `tabs` and `session` storage, then played `steps`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"background": (EXTENSION / "background.js").as_uri(), "steps": list(steps), "tabs": list(tabs), "session": session or {}, "local": local or {}, **cfg}
    out = subprocess.run([node, "--input-type=module", "-e", DRIVER, json.dumps(cfg)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


A, B, C = "http://127.0.0.1:8712", "http://localhost:8713", "http://[::1]:8714"


def assassin(tab_id, origin, token, **tab):
    """An Assassin tab of the server at `origin` carrying `token`."""
    return {"id": tab_id, "url": f"{origin}/?token={token}", **tab}


def bridge(origin):
    return f"ws://{origin.split('//', 1)[1]}/websurf"


def of(run, origin):
    """The sockets opened to the harness at `origin`, oldest first."""
    return [socket for socket in run["sockets"] if socket["url"] == bridge(origin)]


def hello(socket):
    """The token and version of the hello a socket sent first."""
    first = socket["sent"][0]
    assert first["type"] == "hello"
    return first["token"], first["version"]


def results(socket):
    """The results a socket sent, by request id."""
    return {frame["id"]: {key: value for key, value in frame.items() if key not in ("type", "id")} for frame in socket["sent"] if frame["type"] == "result"}


def pages(socket):
    """The page frames a socket sent, as (event, url)."""
    return [(frame["event"], frame["page"]["url"]) for frame in socket["sent"] if frame["type"] == "page"]


def saved(origin, token, tabs, surf=None, placement=None):
    """A session as storage keeps it."""
    return {origin: {"token": token, "tabs": [[tab, token] for tab in tabs], "surf": {"tabId": surf, "placement": placement}}}


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "discover")
def test_the_sessions_are_found_from_the_urls_of_the_tabs_each_loopback_origin_with_a_token_one_bridge_and_a_surf_tab_never_one():
    taken = [assassin(1, A, "abc"), {"id": 2, "url": f"{A}/?item=AI-ASSASSIN&token=abc"}, assassin(3, B, "def"), assassin(4, C, "ghi")]
    left = ["http://192.168.1.5:8712/?token=x", "http://127.0.0.2:8712/?token=x", "http://example.com:8712/?token=x", "https://127.0.0.1:8715/?token=x",
            "http://127.0.0.1:8716/other?token=x", "http://127.0.0.1:8717/", "http://127.0.0.1:8718/?token=", "http://user@127.0.0.1:8719/?token=x"]
    surfing = assassin(20, "http://127.0.0.1:8721", "zzz")  # the AI's surf tab on a page that looks like one
    run = _run([("welcome", origin) for origin in (A, B, C)],
               tabs=[*taken, *({"id": 5 + n, "url": url} for n, url in enumerate(left)), surfing], session={"sessions": saved(A, "abc", [1], 20, "tab")})
    assert sorted(socket["url"] for socket in run["sockets"]) == sorted(bridge(origin) for origin in (A, B, C))
    assert [hello(of(run, origin)[0]) for origin in (A, B, C)] == [("abc", 3), ("def", 3), ("ghi", 3)]
    assert not any(socket["closed"] for socket in run["sockets"])
    assert ["alarm", "websurf-bridge", {"periodInMinutes": 0.5}] in run["log"]


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "follow")
def test_the_tab_strip_is_followed_a_bridge_opening_with_the_first_tab_of_its_origin_and_closing_with_the_last():
    run = _run([("tab", assassin(1, A, "abc")), ("tab", assassin(2, A, "abc")), ("tab", {"id": 1, "url": "https://example.org/"}),
                ("tab", assassin(3, B, "def")), ("close", 2), ("tab", {"id": 4, "url": "https://example.com/?token=abc"})])
    assert [socket["url"] for socket in run["sockets"]] == [bridge(A), bridge(B)]  # several tabs of one server are one session
    assert of(run, A)[0]["closed"] and not of(run, B)[0]["closed"]  # the last tab of A navigated away or closed
    assert _run()["sockets"] == []  # no Assassin tab, no bridge


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "token")
def test_a_newer_token_of_an_origin_replaces_its_bridge_a_dropped_bridge_is_reopened_by_the_alarm_and_an_ended_one_never():
    run = _run([("tab", assassin(1, A, "abc")), ("welcome", A), ("alarm",), ("tab", assassin(2, A, "new")), ("welcome", A), ("drop", A), ("alarm",),
                ("welcome", A), ("close", 1), ("close", 2), ("alarm",)])
    first, replaced, reopened = of(run, A)
    assert hello(first) == ("abc", 3) and first["closed"]  # an open bridge is left alone by the alarm, then replaced by the server's new token
    assert hello(replaced) == ("new", 3) and hello(reopened) == ("new", 3)
    assert reopened["closed"] and len(run["sockets"]) == 3  # closed with the last tab, never reopened after


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "release")
def test_the_surf_tab_of_a_session_ended_is_released_left_open_and_no_longer_driven():
    page = "https://example.org/page"
    run = _run([("tab", assassin(1, A, "abc")), ("welcome", A), ("surf", A, {"id": 1, "action": "open", "url": page}), ("load", 100, page),
                ("close", 1), ("load", 100, page + "#again"), ("tab", assassin(2, A, "abc")), ("welcome", A), ("load", 100, page + "#more"),
                ("surf", A, {"id": 2, "action": "status"})], split=True)
    ended, anew = of(run, A)
    assert ended["closed"] and pages(ended) == [("load", page)]
    assert 100 in run["tabs"] and not [entry for entry in run["log"] if entry[0] == "remove"]  # left open as an ordinary tab
    assert pages(anew) == [] and results(anew)[2] == {"ok": False, "error": "no surf tab open"}


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "persist")
def test_the_map_outlives_a_restart_of_the_background_in_session_storage_the_tokens_never_in_local_storage():
    page = "https://example.org/page"
    first = _run([("tab", assassin(1, A, "abc")), ("welcome", A), ("surf", A, {"id": 1, "action": "open", "url": page}), ("load", 100, page)], split=True)
    assert first["stored"]["session"] == {"sessions": saved(A, "abc", [1], 100, "split")}
    assert "abc" not in json.dumps(first["stored"]["local"])
    restarted = _run([("welcome", A), ("surf", A, {"id": 2, "action": "status"})],
                     tabs=[assassin(1, A, "abc"), {"id": 100, "url": page, "title": "Page"}], session=first["stored"]["session"])
    assert results(of(restarted, A)[0])[2] == {"ok": True, "page": {"url": page, "title": "Page", "status": None, "content_type": None}}
    fallback = _run([("tab", assassin(1, A, "abc"))], noSession=True)  # a browser without session storage keeps the map locally
    assert fallback["stored"]["local"]["sessions"] == saved(A, "abc", [1])


@pytest.mark.syngate("BROWSER-EXTENSION-SESSION", "status")
def test_the_sessions_are_shown_read_only_the_badge_counting_those_connected_nothing_being_typed():
    run = _run([("tab", assassin(1, A, "abc")), ("tab", assassin(2, B, "def")), ("welcome", A), ("welcome", B), ("surf", A, {"id": 1, "action": "close"}),
                ("drop", B), ("click",)])
    assert run["stored"]["local"]["status"] == [{"origin": A, "bridge": "connected", "surf": None}, {"origin": B, "bridge": "disconnected", "surf": None}]
    badges = [entry[1] for entry in run["log"] if entry[0] == "badge"]
    assert badges[badges.index("2"):] == ["2", "●", "2", "1"] and ["options"] in run["log"]
    page = (EXTENSION / "options.html").read_text(encoding="utf-8")
    assert not re.search(r"<(input|textarea|form)\b", page) and 'id="grant"' in page
    assert "harnessConfig" not in (EXTENSION / "bridge.js").read_text(encoding="utf-8") + (EXTENSION / "options.js").read_text(encoding="utf-8")


@pytest.mark.syngate("BROWSER-EXTENSION-ISOLATION", "requests")
def test_the_requests_of_a_session_act_on_its_own_surf_tab_alone_placed_beside_its_own_assassin_tab():
    one, two = "https://example.org/one", "https://example.org/two"
    run = _run([("welcome", A), ("welcome", B), ("surf", A, {"id": 1, "action": "open", "url": one}), ("surf", B, {"id": 1, "action": "open", "url": two}),
                ("load", 100, one), ("load", 101, two), ("surf", A, {"id": 2, "action": "query", "origin": "https://example.org"}),
                ("surf", B, {"id": 2, "action": "close"}), ("surf", A, {"id": 3, "action": "status"}), ("surf", B, {"id": 3, "action": "status"})],
               tabs=[assassin(1, A, "abc", windowId=1), assassin(2, B, "def", windowId=2)], split=True)
    assert [entry[1] for entry in run["log"] if entry[0] == "create"] == [{"url": one, "splitWithTabId": 1}, {"url": two, "splitWithTabId": 2}]
    assert [entry[1:] for entry in run["log"] if entry[0] in ("inject", "remove")] == [[100, "query"], [101]]
    mine, theirs = results(of(run, A)[0]), results(of(run, B)[0])
    assert mine[1]["page"]["url"] == one and theirs[1]["page"]["url"] == two
    assert mine[3]["page"]["url"] == one and theirs[3] == {"ok": False, "error": "no surf tab open"}


@pytest.mark.syngate("BROWSER-EXTENSION-ISOLATION", "events")
def test_the_page_events_of_a_surf_tab_go_to_the_bridge_of_its_session_alone():
    one, two = "https://example.org/one", "https://example.org/two"
    run = _run([("welcome", A), ("welcome", B), ("load", 100, one), ("load", 101, two), ("load", 7, "https://example.com/elsewhere"), ("close", 101)],
               tabs=[assassin(1, A, "abc"), assassin(2, B, "def"), {"id": 100, "url": "about:blank"}, {"id": 101, "url": "about:blank"},
                     {"id": 7, "url": "https://example.com/"}],
               session={"sessions": {**saved(A, "abc", [1], 100, "split"), **saved(B, "def", [2], 101, "split")}})
    assert pages(of(run, A)[0]) == [("load", one)]
    assert pages(of(run, B)[0]) == [("load", two), ("closed", two)]
