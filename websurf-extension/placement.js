// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

import { assassinSession } from './sessions.js';

// The placement of a new window by the harness's tiling methods under which the browser cannot position its windows: the Assassin
// window left as it is, the compositor tiling the new one under `kwin`, the desktop placing it under `none`.
const UNPOSITIONED = { kwin: 'tiled', none: 'window' };

/** Returns the label `WebSurf <port> · ` set in front of the title of every surf window of the session of the harness at `origin`. */
export function windowLabel(origin) {
  return `WebSurf ${new URL(origin).port || '80'} · `;
}

/**
 * Opens `url` beside the Assassin tab of the session of the harness at `origin`, else as the active tab of the window `windowId` of the
 * surf tab it replaces or of the current one, as a surf tab out of sight serves no request; a new window is tiled by the browser under
 * the `tiling` method `browser`, else left to the compositor or the desktop. Returns `{placement: 'split'|'tiled'|'window'|'tab', tab|window}`,
 * with `tile` -- the titles finding the new window and the Assassin window -- for the compositor under `kwin`.
 */
export async function placeSurfTab(browser, url, origin, windowId, tiling = 'browser') {
  const assassin = (await browser.tabs.query({})).find((t) => (assassinSession(t.url || '') || {}).origin === origin);
  if (!assassin) return { placement: 'tab', tab: await browser.tabs.create({ url, active: true, ...(windowId == null ? {} : { windowId }) }) };
  if (typeof browser.tabs.createSplit === 'function') {
    try {
      return { placement: 'split', tab: await browser.tabs.create({ url, splitWithTabId: assassin.id }) };
    } catch (e) {
      // a refused split falls back to tiled windows
    }
  }
  // Firefox, which tells its runtime.getBrowserInfo, takes titlePreface; Chrome refuses a property it does not know
  const label = typeof (browser.runtime || {}).getBrowserInfo === 'function' ? { titlePreface: windowLabel(origin) } : {};
  if (Object.hasOwn(UNPOSITIONED, tiling)) {
    const placed = { placement: UNPOSITIONED[tiling], window: await browser.windows.create({ url, ...label }) };
    // the Assassin tab's title is its window's caption only while it is the active tab there
    if (tiling === 'kwin' && label.titlePreface) placed.tile = { surf: label.titlePreface, assassin: (assassin.active && assassin.title) || null };
    return placed;
  }
  const { left, top, width, height } = await browser.windows.get(assassin.windowId);
  const wide = width >= height;
  const first = wide ? Math.floor(width / 2) : Math.floor(height / 2);
  await browser.windows.update(assassin.windowId, wide ? { left, top, width: first, height } : { left, top, width, height: first });
  const second = wide
    ? { left: left + first, top, width: width - first, height }
    : { left, top: top + first, width, height: height - first };
  return { placement: 'tiled', window: await browser.windows.create({ url, ...label, ...second }) };
}
