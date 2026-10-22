# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/bridge.js` run by node against a fake WebSocket recording the frames sent, and `background.js` serving the bridge's
requests against a mock `browser` -- [BROWSER-EXTENSION-BRIDGE]."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "websurf-extension" / "bridge.js"
DRIVER = """
import { openBridge } from %s;
const cfg = JSON.parse(process.argv[1]);
const sent = [], statuses = [];
class FakeSocket {
  constructor(url) { this.url = url; this.readyState = 0; }
  send(data) { sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; if (this.onclose) this.onclose(); }
}
// the session of an Assassin tab at this URL: its harness origin and the token the URL carries
const page = new URL(cfg.input);
const config = { origin: page.origin, token: page.searchParams.get('token') || cfg.token };
const handle = async (request) => {
  if (request.url.includes('fail')) throw new Error('boom');
  return { ok: true, url: request.url, text: 'page' };
};
const socket = openBridge(FakeSocket, { ...config, agent: 'test-agent', pingMs: cfg.pingMs }, handle, (s) => statuses.push(s));
socket.readyState = 1;
socket.onopen();
for (const frame of cfg.frames || []) {
  if (frame.report) socket.report(frame.report);
  else await socket.onmessage({ data: JSON.stringify(frame) });
}
if (cfg.waitMs) await new Promise((resolve) => setTimeout(resolve, cfg.waitMs));
socket.close();
console.log(JSON.stringify({ url: socket.url, config, sent, statuses }));
"""


BACKGROUND = """
const cfg = JSON.parse(process.argv[1]);
const log = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const event = () => {
  const listeners = new Set();
  return { addListener: (l) => listeners.add(l), removeListener: (l) => listeners.delete(l), fire: (...args) => [...listeners].forEach((l) => l(...args)) };
};
const tabs = new Map([[7, { id: 7, windowId: 3, index: 0, active: true, splitViewId: -1, url: 'https://example.org/old', title: 'Old' }]]);
let nextId = 100;
const removed = event(), nav = {};
for (const name of ['onBeforeNavigate', 'onCommitted', 'onCompleted', 'onErrorOccurred', 'onHistoryStateUpdated', 'onReferenceFragmentUpdated']) nav[name] = event();
// the browser as the background finds it: the Assassin tab 1 of a session whose surf tab 7 is kept from before, tabs created after a
// while, scripts that never answer in `hang`
tabs.set(1, { id: 1, windowId: 3, index: 1, active: false, splitViewId: -1, url: 'http://127.0.0.1:8712/?token=abc', title: 'AI Assassin' });
const saved = { 'http://127.0.0.1:8712': { token: 'abc', tabs: [[1, 'abc']], surf: { tabId: 7, placement: 'tiled' } } };
globalThis.chrome = {
  storage: {
    local: { get: async (defaults) => ({ ...defaults }), set: async () => {} },
    session: { get: async (defaults) => ({ ...defaults, sessions: saved }), set: async () => {} },
    onChanged: event(),
  },
  action: { setBadgeText: ({ text }) => log.push(['badge', text]), onClicked: event() },
  runtime: { onInstalled: event(), onStartup: event(), openOptionsPage: () => {} },
  alarms: { onAlarm: event(), create: () => {} },
  tabs: {
    query: async () => [...tabs.values()].map((tab) => ({ ...tab })),
    get: async (id) => { if (!tabs.has(id)) throw new Error(`no tab ${id}`); return { ...tabs.get(id) }; },
    create: async (props) => {
      log.push(['create', props.url]);
      await sleep(cfg.createMs);
      const tab = { id: nextId++, windowId: props.windowId, index: props.index, active: true, splitViewId: -1, url: '', pendingUrl: props.url, title: '' };
      tabs.set(tab.id, tab);
      log.push(['created', props.url]);
      return { ...tab };
    },
    remove: async (id) => { log.push(['remove', id]); tabs.delete(id); removed.fire(id, {}); },
    onUpdated: event(),
    onRemoved: removed,
  },
  windows: { get: async (id) => ({ id, state: 'normal' }) },
  webNavigation: nav,
  webRequest: { onCompleted: event() },
  scripting: {
    executeScript: ({ target, args }) => {
      log.push(['inject', args[0], target.tabId]);
      return cfg.hang.includes(args[0]) ? new Promise(() => {}) : Promise.resolve([{ frameId: 0, result: {} }]);
    },
  },
};
const sockets = [];
globalThis.WebSocket = class {
  constructor(url) { this.url = url; this.readyState = 0; sockets.push(this); }
  send(data) { const frame = JSON.parse(data); if (frame.type === 'result') log.push(['result', frame.id, frame.ok, frame.error || null]); }
  close() {}
};
await import(cfg.background);
while (!sockets.length) await sleep(1);
const [socket] = sockets;
socket.readyState = 1;
socket.onopen();
await socket.onmessage({ data: JSON.stringify({ type: 'welcome' }) });
log.length = 0;
for (const frame of cfg.frames) socket.onmessage({ data: JSON.stringify({ type: 'surf', ...frame }) });
await sleep(cfg.afterMs);
console.log(JSON.stringify({ log }));
process.exit(0);
"""


def _background(frames, hang=(), create_ms=20, after_ms=200):
    """Return the log -- badge texts, tab creations and removals, injections and results -- of `background.js` serving `frames` sent at
    once over its bridge, under node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"background": (ROOT / "websurf-extension" / "background.js").as_uri(), "frames": list(frames), "hang": list(hang),
           "createMs": create_ms, "afterMs": after_ms}
    out = subprocess.run([node, "--input-type=module", "-e", BACKGROUND, json.dumps(cfg)], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)["log"]


def _bridge(input_url, token="", frames=(), ping_ms=None, wait_ms=0):
    """Return the socket URL, the parsed config, the frames sent and the statuses of one bridge run under node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"input": input_url, "token": token, "frames": list(frames), "pingMs": ping_ms, "waitMs": wait_ms}
    out = subprocess.run([node, "--input-type=module", "-e", DRIVER % json.dumps(BRIDGE.as_uri()), json.dumps(cfg)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "hello")
def test_the_bridge_of_a_session_connects_to_the_websurf_path_of_its_harness_origin_and_introduces_itself_with_its_token():
    run = _bridge("http://127.0.0.1:8712/?token=abc")
    assert run["url"] == "ws://127.0.0.1:8712/websurf"
    assert run["sent"][0] == {"type": "hello", "token": "abc", "version": 3, "agent": "test-agent"}
    for origin in ("localhost:8713", "[::1]:8714"):
        assert _bridge(f"http://{origin}/?token=xyz")["url"] == f"ws://{origin}/websurf"


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "answer")
def test_the_bridge_answers_each_surf_request_and_sends_page_frames_only_once_welcomed():
    early = {"type": "page", "event": "history", "page": {"url": "https://example.org/#a", "title": "", "status": None, "content_type": None}}
    page = {"type": "page", "event": "load", "page": {"url": "https://example.org/", "title": "T", "status": 200, "content_type": "text/html"}}
    run = _bridge("http://127.0.0.1:8712/?token=abc", frames=[
        {"report": early},
        {"type": "surf", "id": 1, "action": "open", "url": "https://example.org/"},
        {"type": "welcome"},
        {"type": "surf", "id": 2, "action": "open", "url": "https://example.org/"},
        {"report": page},
        {"type": "surf", "id": 3, "action": "open", "url": "https://example.org/fail"},
    ])
    results = {frame["id"]: frame for frame in run["sent"] if frame["type"] == "result"}
    assert results[1]["ok"] is False and "authenticated" in results[1]["error"]
    assert results[2] == {"type": "result", "id": 2, "ok": True, "url": "https://example.org/", "text": "page"}
    assert results[3]["ok"] is False and results[3]["error"] == "boom"
    assert [frame for frame in run["sent"] if frame["type"] == "page"] == [page]
    assert "connected" in run["statuses"] and run["statuses"][-1] == "disconnected"


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "ping")
def test_the_bridge_pings_the_harness_to_stay_alive_and_answers_its_pings():
    run = _bridge("http://127.0.0.1:8712/?token=abc", frames=[{"type": "ping"}], ping_ms=20, wait_ms=90)
    assert {"type": "pong"} in run["sent"]
    assert {"type": "ping"} in run["sent"]


@pytest.mark.syngate("BROWSER-EXTENSION-BRIDGE", "unheld")
def test_page_actions_run_as_they_come_and_never_hold_back_an_open_or_close_which_run_one_at_a_time():
    a, b = "https://example.org/a", "https://example.org/b"
    log = _background([{"id": 1, "action": "query", "origin": "https://example.org"}, {"id": 2, "action": "open", "url": a},
                       {"id": 3, "action": "open", "url": b}, {"id": 4, "action": "status"}, {"id": 5, "action": "close"}], hang=["query"])
    at = {tuple(entry[:2]): index for index, entry in enumerate(log)}
    results = {entry[1]: entry for entry in log if entry[0] == "result"}
    assert sorted(results) == [1, 2, 3, 4, 5] and [results[n][2] for n in (2, 3, 4, 5)] == [True] * 4
    assert results[1][2] is False and "went away" in results[1][3]
    assert at[("result", 4)] < at[("created", a)] < at[("remove", 7)] < at[("create", b)] < at[("created", b)] < at[("remove", 100)] < at[("remove", 101)]
    assert [entry for entry in log if entry[0] == "badge"] == [["badge", "●"], ["badge", "1"]] and at[("badge", "1")] > at[("remove", 101)]
