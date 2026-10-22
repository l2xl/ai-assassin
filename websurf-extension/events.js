// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

const UNKNOWN = { url: null, title: '', status: null, content_type: null };

/**
 * Returns the page info of the surf tab -- its URL (`url` if given, else that of the navigation pending in a tab with no document yet)
 * and title, its document's HTTP status and content type, null where none was reported -- kept as the last known.
 */
export async function pageInfo(api, state, url) {
  const tab = await api.tabs.get(state.tabId);
  const response = state.response || {};
  state.page = { url: url || tab.url || tab.pendingUrl || null, title: tab.title || '', status: response.status ?? null, content_type: response.content_type ?? null };
  return state.page;
}

/**
 * Sends each change of a surf tab's document -- and each of its navigations that failed, with the browser's error -- through `emit` as a
 * page frame with the surf tab it is of, `owner(tabId)` telling the surf tab a tab is, else null, its main frame's response joined into
 * the page info; registers at once, as a background woken by an event needs.
 */
export function watchSurfTabs(api, owner, emit) {
  // By tab, the response of the navigation under way, the document's own once it has loaded; a document restored from the back/forward cache has none.
  const fresh = new Map();
  let queue = Promise.resolve();
  const surfed = (details) => (details.frameId === 0 && details.url !== 'about:blank' && owner(details.tabId)) || null;
  const later = (step) => { queue = queue.then(step).catch(() => {}); };
  const report = (state, event, url, extra = {}) => later(async () => emit(state, { type: 'page', event, page: await pageInfo(api, state, url), ...extra }));
  api.webRequest.onCompleted.addListener((details) => {
    const type = (details.responseHeaders || []).find((header) => header.name.toLowerCase() === 'content-type');
    if (owner(details.tabId)) fresh.set(details.tabId, { status: details.statusCode, content_type: type ? type.value : null });
  }, { urls: ['<all_urls>'], types: ['main_frame'] }, ['responseHeaders']);
  api.webNavigation.onBeforeNavigate.addListener((details) => { if (surfed(details)) fresh.delete(details.tabId); });
  api.webNavigation.onCompleted.addListener((details) => {
    const state = surfed(details);
    if (!state) return;
    state.response = fresh.get(details.tabId) || null;
    fresh.delete(details.tabId);
    report(state, 'load', details.url);
  });
  // a navigation that failed loaded no document of its own: its page info knows no response
  api.webNavigation.onErrorOccurred.addListener((details) => {
    const state = surfed(details);
    if (!state) return;
    state.response = null;
    fresh.delete(details.tabId);
    report(state, 'failed', details.url, { error: String(details.error || 'the navigation failed') });
  });
  for (const changed of [api.webNavigation.onHistoryStateUpdated, api.webNavigation.onReferenceFragmentUpdated]) {
    changed.addListener((details) => {
      const state = surfed(details);
      if (state) report(state, 'history', details.url);
    });
  }
  api.tabs.onRemoved.addListener((tabId) => {
    const state = owner(tabId);
    fresh.delete(tabId);
    if (!state) return;
    state.tabId = null;
    later(() => {
      emit(state, { type: 'page', event: 'closed', page: state.page || UNKNOWN });
      if (state.tabId === null) state.page = state.response = null;
    });
  });
}

/** Sends each change of the one surf tab `state` through `emit` as a page frame, as `watchSurfTabs` does. */
export function watchSurfTab(api, state, emit) {
  watchSurfTabs(api, (tabId) => (tabId != null && tabId === state.tabId ? state : null), (surfTab, frame) => emit(frame));
}
