// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

import { openBridge } from './bridge.js';
import { surf } from './surf.js';
import { watchSurfTabs } from './events.js';
import { assassinSession } from './sessions.js';

const api = globalThis.browser ?? globalThis.chrome;
// The map holds the tokens: in the browser's session storage, kept in memory and gone with the browser, where it has one.
const store = api.storage.session ?? api.storage.local;
// The requests that replace or end a session's surf tab, run one at a time; a page action runs as it comes, so none -- however stuck its
// page -- holds back the `open` or `close` that replaces or ends its tab.
const TAB_ACTIONS = ['open', 'close'];

// The AI Assassin sessions open in this browser by harness origin, found from the URLs of their tabs: each its token, its Assassin tabs
// with the token each carries, its bridge and its surf tab; the tokens, tab ids and placements outlive a restart of the background.
const sessions = new Map();
let seen = 0;
let running = 0;
let badge = null;
let scanning = true;

/** Returns a session of the harness at `origin` with no tab, bridge or surf tab yet. */
function session(origin) {
  return { origin, token: null, tabs: new Map(), socket: null, status: 'disconnected', surf: { tabId: null, placement: null, response: null, page: null },
           replacing: Promise.resolve() };
}

/** Returns the session whose surf tab `tabId` is, else undefined. */
function surfing(tabId) {
  if (tabId == null) return undefined;
  return [...sessions.values()].find((s) => s.surf.tabId === tabId);
}

/** Shows ● on the badge while a request runs, else the number of sessions connected. */
function showBadge() {
  const connected = [...sessions.values()].filter((s) => s.status === 'connected').length;
  const text = running ? '●' : connected ? String(connected) : '';
  if (text !== badge) api.action.setBadgeText({ text });
  badge = text;
}

/** Keeps the map -- tokens, tab ids, placements -- in storage, and the token-free status of every session for the options page. */
function save() {
  const map = {}, status = [];
  for (const s of sessions.values()) {
    map[s.origin] = { token: s.token, tabs: [...s.tabs].map(([id, tab]) => [id, tab.token]), surf: { tabId: s.surf.tabId, placement: s.surf.placement } };
    status.push({ origin: s.origin, bridge: s.status, surf: s.surf.tabId });
  }
  showBadge();
  return Promise.all([store.set({ sessions: map }), api.storage.local.set({ status })]).catch(() => {});
}

/** Opens the session's bridge, introduced with its token, unless one is open or opening. */
function connect(s) {
  if (!s.token || (s.socket && s.socket.readyState <= 1)) return;
  const socket = openBridge(WebSocket, { origin: s.origin, token: s.token, agent: navigator.userAgent }, (request) => handle(s, request), (status) => {
    if (s.socket !== socket || sessions.get(s.origin) !== s) return;
    s.status = status;
    save();
  });
  s.socket = socket;
  s.status = 'connecting';
  save();
}

/** Closes the session's bridge, its closing no longer told. */
function disconnect(s) {
  const socket = s.socket;
  s.socket = null;
  s.status = 'disconnected';
  if (socket) socket.close();
}

/** Ends a session: its bridge closed and its surf tab released, left open as an ordinary tab no longer driven. */
function end(s) {
  if (sessions.get(s.origin) === s) sessions.delete(s.origin);
  disconnect(s);
  save();
}

/** Brings a session in line with its Assassin tabs: its token that of the tab seen last, a new one replacing the bridge, the bridge open; one left with no tab ends. */
function settle(s) {
  if (!s.tabs.size) return end(s);
  const [, newest] = [...s.tabs].reduce((last, entry) => (entry[1].seen > last[1].seen ? entry : last));
  if (newest.token !== s.token) {
    s.token = newest.token;
    disconnect(s);
  }
  connect(s);
  return save();
}

/** Takes note of a tab's URL: an Assassin tab -- never a surf tab -- joins the session of its origin, a tab no longer one leaves its own. */
function note(tabId, url) {
  const found = surfing(tabId) ? null : assassinSession(url || '');
  for (const s of [...sessions.values()]) {
    if (s.tabs.has(tabId) && (!found || found.origin !== s.origin)) {
      s.tabs.delete(tabId);
      if (!scanning) settle(s);
    }
  }
  if (!found) return;
  if (!sessions.has(found.origin)) sessions.set(found.origin, session(found.origin));
  const s = sessions.get(found.origin);
  const known = s.tabs.get(tabId);
  if (!known || known.token !== found.token) s.tabs.set(tabId, { token: found.token, seen: ++seen });
  if (!scanning) settle(s);
}

/** Lets a closed tab go from the session it was an Assassin tab of. */
function forget(tabId) {
  for (const s of [...sessions.values()]) if (s.tabs.delete(tabId)) settle(s);
}

/** Takes a tab that has become a surf tab out of any session it was taken into as an Assassin tab. */
function purge() {
  for (const s of [...sessions.values()]) {
    for (const tabId of [...s.tabs.keys()]) {
      if (!surfing(tabId)) continue;
      s.tabs.delete(tabId);
      settle(s);
    }
  }
}

/** Returns the answer to a surf request of the session, on its surf tab: an `open` or `close` run after its ones before, a page action at once. */
function handle(s, request) {
  if (running++ === 0) showBadge();
  const run = async () => {
    await ready;
    return surf(api, request, { origin: s.origin }, s.surf);
  };
  const answer = TAB_ACTIONS.includes(request.action) ? (s.replacing = s.replacing.then(run, run)) : run();
  return answer.finally(() => {
    running -= 1;
    purge();
    return save();
  });
}

/** Sends a page frame of a surf tab to the bridge of the session owning it alone. */
function report(surfTab, frame) {
  const s = [...sessions.values()].find((each) => each.surf === surfTab);
  if (!s) return;
  if (s.socket) s.socket.report(frame);
  if (frame.event === 'closed') save();
}

/** Reopens every bridge dropped, as an engine restart keeps the port and the token. */
function reconnect() {
  return ready.then(() => { for (const s of sessions.values()) connect(s); });
}

// The map as the background left it, then the tab strip as it is: the Assassin tabs, the most recently used last so its token wins.
const ready = (async () => {
  const saved = (await store.get({ sessions: {} }).catch(() => ({}))).sessions || {};
  for (const [origin, entry] of Object.entries(saved)) {
    const s = session(origin);
    s.token = entry.token || null;
    Object.assign(s.surf, { tabId: (entry.surf && entry.surf.tabId) ?? null, placement: (entry.surf && entry.surf.placement) ?? null });
    sessions.set(origin, s);
  }
  const tabs = await api.tabs.query({}).catch(() => []);
  tabs.sort((a, b) => (a.lastAccessed || 0) - (b.lastAccessed || 0));
  for (const tab of tabs) note(tab.id, tab.url);
  scanning = false;
  for (const s of [...sessions.values()]) settle(s);
  await save();
})();

watchSurfTabs(api, (tabId) => (surfing(tabId) || {}).surf || null, report);
api.tabs.onUpdated.addListener((tabId, change) => { if (change.url) ready.then(() => note(tabId, change.url)); });
api.tabs.onRemoved.addListener((tabId) => { ready.then(() => forget(tabId)); });
api.runtime.onInstalled.addListener(reconnect);
api.runtime.onStartup.addListener(reconnect);
api.alarms.onAlarm.addListener(reconnect);
api.action.onClicked.addListener(() => api.runtime.openOptionsPage());
api.alarms.create('websurf-bridge', { periodInMinutes: 0.5 });
