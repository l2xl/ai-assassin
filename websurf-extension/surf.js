// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

import { placeSurfTab } from './placement.js';
import { pageInfo } from './events.js';
import { pageAction } from './page.js';

const ACTIONS = { open, close, status, query, screenshot, fill, mouse };
// the actions played in the page, each naming the origin of the page it is meant for
const PAGE_ACTIONS = [query, screenshot, fill, mouse];
const JPEG_QUALITY = 0.8;

/**
 * Returns the answer to one surf request of the session of the harness at `config.origin`, acting on its surf tab `state` alone and
 * carrying its page info; while none is open every action but `open` is refused, and while it is out of the user's sight every action
 * is, without page info. No answer waits on a page load: what the page does after it reaches the harness as page events.
 */
export async function surf(api, request, config, state) {
  const act = Object.hasOwn(ACTIONS, request.action) && ACTIONS[request.action];
  if (!act) return { ok: false, error: `unknown action ${request.action}` };
  const tab = state.tabId != null && (await api.tabs.get(state.tabId).catch(() => null));
  if (!tab) {
    state.tabId = null;
    if (act !== open) return { ok: false, error: 'no surf tab open' };
  } else {
    const why = await hidden(api, tab);
    if (why) return hiddenRefusal(why);
  }
  if (PAGE_ACTIONS.includes(act) && typeof request.origin !== 'string') {
    return { ok: false, error: `${request.action} names no origin of the page it is meant for` };
  }
  try {
    return await act(api, request, config, state, tab);
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e), page: await pageInfo(api, state).catch(() => undefined) };
  }
}

/** The refusal of every request while the surf tab is out of the user's sight, `why` telling how; it carries no page info. */
function hiddenRefusal(why) {
  return { ok: false, error: `the surf tab is hidden (${why}): every request is refused until the user shows it again or closes it` };
}

/** Whether the tab shares a split view with another. */
function split(tab) {
  return tab.splitViewId != null && tab.splitViewId !== -1;
}

/**
 * Returns why the tab is out of the user's sight by its own state -- its window minimized, hidden by the browser, behind another tab of
 * its window and in no split view -- or null while it shows. The page's own word, which also covers an occluded window and a split view
 * behind another tab, is asked by a page action in the very script that plays it.
 */
async function hidden(api, tab) {
  const win = await api.windows.get(tab.windowId).catch(() => null);
  if (win && win.state === 'minimized') return 'its window is minimized';
  if (tab.hidden) return 'the browser hides it';
  if (!tab.active && !split(tab)) return 'another tab is in front of it';
  return null;
}

/** Makes `tabId` the surf tab under `placement`, with no document known yet. */
function adopt(state, tabId, placement) {
  Object.assign(state, { tabId, placement, response: null, page: null });
}

/** Closes the tab, one already gone counting as closed. */
async function closeTab(api, tabId) {
  try {
    await api.tabs.remove(tabId);
  } catch (e) {
    if (await api.tabs.get(tabId).catch(() => null)) throw e;
  }
}

/**
 * Loads an http(s) URL in a new surf tab, so no history, session storage or script state of the previous one carries over, and answers
 * as soon as the tab exists, with the page info of its pending document -- the URL asked for, its status and content type not yet
 * known; the load reaches the harness as page events. The new tab takes the previous one's place -- in its window, at its index, under
 * its placement -- and is opened before that one is closed, so a tiled window survives and no window is tiled or focused anew; one in a
 * split view is closed first and its successor placed beside the session's Assassin tab, as the first surf tab is, under the harness's
 * `tiling` method, the answer of a new window carrying the `tile` the compositor finds it by.
 */
async function open(api, request, config, state, tab) {
  const url = new URL(request.url);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return { ok: false, error: `refused scheme ${url.protocol}` };
  let tile = null;
  if (tab && !split(tab)) {
    const created = await api.tabs.create({ url: url.href, windowId: tab.windowId, index: tab.index, active: true });
    adopt(state, created.id, state.placement || 'tab');
    await closeTab(api, tab.id);
  } else {
    if (tab) {
      // no longer the surf tab while it closes, so its closing is no page event; still the surf tab where it does not close
      state.tabId = null;
      await closeTab(api, tab.id).catch((e) => { state.tabId = tab.id; throw e; });
    }
    const placed = await placeSurfTab(api, url.href, config.origin, tab ? tab.windowId : undefined, request.tiling || 'browser');
    adopt(state, placed.tab ? placed.tab.id : placed.window.tabs[0].id, placed.placement);
    tile = placed.tile || null;
  }
  const page = await pageInfo(api, state);
  // Chrome tells the navigation not yet committed as the tab's pendingUrl, Firefox shows about:blank meanwhile
  if (!page.url || page.url === 'about:blank') page.url = url.href;
  return { ok: true, page, placement: state.placement, ...(tile ? { tile } : {}) };
}

/** Closes the surf tab; its closing reaches the harness as the `closed` page event. */
async function close(api, request, config, state, tab) {
  await closeTab(api, tab.id);
  return { ok: true };
}

/** Answers the page info of the surf tab as it is now. */
async function status(api, request, config, state) {
  return { ok: true, page: await pageInfo(api, state) };
}

/** Returns the answer a page's refusal of an action makes -- hidden, without page info, or of another origin, with it -- else null. */
async function refusal(api, state, found) {
  if (found.hidden) return hiddenRefusal(found.hidden);
  if (found.error) return { ok: false, error: found.error, page: await pageInfo(api, state) };
  return null;
}

/** Answers the serialized live DOM of the selector's matches, or of the whole document, cut to `max_chars`. */
async function query(api, request, config, state) {
  const found = await inPage(api, state.tabId, 'query', { selector: request.selector ?? null, max_chars: request.max_chars ?? null, origin: request.origin });
  return (await refusal(api, state, found)) || { ok: true, page: await pageInfo(api, state), dom: found.dom, matches: found.matches, truncated: found.truncated };
}

/**
 * Answers the visible part of the surf tab, activated in its window -- the inactive pane of a split view takes the front -- with every
 * visible sensitive element masked in every frame, as a JPEG fitted by `fit`, with the viewport, its device pixel scale and the image's.
 */
async function screenshot(api, request, config, state, tab) {
  await api.tabs.update(tab.id, { active: true });
  let top, captured, away = false;
  try {
    const frames = await inject(api, tab.id, 'mask', { on: true, origin: request.origin }, true).catch((e) => { away = Boolean(e.gone); throw e; });
    top = topResult(frames);
    // the boxes laid in any frame are painted by two frames of the top one, which a frame out of sight would never render
    if (!top.hidden && !top.error && frames.some((frame) => frame.result && frame.result.masked > 0)) {
      const painted = await inPage(api, tab.id, 'paint', { origin: request.origin }).catch((e) => { away = Boolean(e.gone); throw e; });
      if (painted.hidden || painted.error) top = painted;
    }
    if (!top.hidden && !top.error) captured = await api.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  } finally {
    // the boxes go with a document that went away; one still there has them taken away, as its going answers that too
    if (!away) await inject(api, tab.id, 'mask', { on: false }, true).catch(() => {});
  }
  const refused = await refusal(api, state, top);
  if (refused) return refused;
  const { image, scale: imageScale } = await fit(captured, top.viewport, request);
  return { ok: true, page: await pageInfo(api, state), image, viewport: top.viewport, scale: top.scale, image_scale: imageScale };
}

/**
 * Returns the captured image data URL as a JPEG data URL scaled to the viewport's CSS pixels, or below them to fit `max_edge` (its
 * longest side) and `max_pixels` (its area), never above them, with its scale -- image pixels per CSS pixel.
 */
async function fit(captured, viewport, { max_edge: edge, max_pixels: pixels }) {
  const [head, data] = String(captured).split(',', 2);
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
  const bitmap = await createImageBitmap(new Blob([bytes], { type: head.slice(5).split(';')[0] }));
  const width = (viewport && viewport.width) || bitmap.width, height = (viewport && viewport.height) || bitmap.height;
  let scale = 1;
  if (Number.isFinite(edge) && edge > 0) scale = Math.min(scale, edge / Math.max(width, height));
  if (Number.isFinite(pixels) && pixels > 0) scale = Math.min(scale, Math.sqrt(pixels / (width * height)));
  const canvas = new OffscreenCanvas(Math.max(1, Math.floor(width * scale)), Math.max(1, Math.floor(height * scale)));
  const context = canvas.getContext('2d');
  context.imageSmoothingQuality = 'high';
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const jpeg = new Uint8Array(await (await canvas.convertToBlob({ type: 'image/jpeg', quality: JPEG_QUALITY })).arrayBuffer());
  let text = '';
  for (let i = 0; i < jpeg.length; i += 0x8000) text += String.fromCharCode(...jpeg.subarray(i, i + 0x8000));
  return { image: `data:image/jpeg;base64,${btoa(text)}`, scale };
}

/** Fills the first element the selector matches as typing would, and answers once it has played, with the page info as it then is. */
async function fill(api, request, config, state) {
  const found = await inPage(api, state.tabId, 'fill', { selector: String(request.selector ?? ''), value: String(request.value ?? ''), origin: request.origin });
  return (await refusal(api, state, found)) || { ok: true, page: await pageInfo(api, state) };
}

/** Plays the mouse steps in the page, and answers once they have played, with the page info as it then is. */
async function mouse(api, request, config, state) {
  const found = await inPage(api, state.tabId, 'mouse', { steps: request.steps, origin: request.origin });
  return (await refusal(api, state, found)) || { ok: true, page: await pageInfo(api, state) };
}

/** Returns what `pageAction` answers in the top frame among the injection results. */
function topResult(frames) {
  return ((frames || []).find((frame) => frame.frameId === 0) || {}).result || {};
}

/** Returns what `pageAction` answers in the top frame of the tab. */
async function inPage(api, tabId, action, options) {
  return topResult(await inject(api, tabId, action, options));
}

/**
 * Returns the injection results of `pageAction` played in the tab's top frame, or in every frame with `allFrames`, or throws an error
 * marked `gone` once the tab's document goes away while it plays -- a new document committed in its top frame, or the tab closed --
 * as the browser may never answer for it.
 */
async function inject(api, tabId, action, options, allFrames = false) {
  let stop;
  const gone = new Promise((resolve, reject) => {
    const away = (why) => reject(Object.assign(new Error(`the page went away while the ${action} played: ${why}`), { gone: true }));
    const committed = (details) => { if (details.tabId === tabId && details.frameId === 0) away('a new document committed in the surf tab'); };
    const removed = (id) => { if (id === tabId) away('the surf tab was closed'); };
    api.webNavigation.onCommitted.addListener(committed);
    api.tabs.onRemoved.addListener(removed);
    stop = () => {
      api.webNavigation.onCommitted.removeListener(committed);
      api.tabs.onRemoved.removeListener(removed);
    };
  });
  try {
    const target = allFrames ? { tabId, allFrames: true } : { tabId };
    return await Promise.race([api.scripting.executeScript({ target, func: pageAction, args: [action, options] }), gone]);
  } finally {
    stop();
  }
}
