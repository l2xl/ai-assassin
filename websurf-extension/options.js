// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

/** Shows the sessions the background records -- each its harness origin, its bridge and its surf tab -- read only. */
function showSessions(sessions) {
  const list = Array.isArray(sessions) ? sessions : [];
  const rows = list.map(({ origin, bridge, surf }) => {
    const row = document.createElement('tr');
    for (const text of [origin, bridge, surf == null ? 'none' : `tab ${surf}`]) row.appendChild(document.createElement('td')).textContent = String(text);
    return row;
  });
  $('sessions').querySelector('tbody').replaceChildren(...rows);
  $('sessions').hidden = !rows.length;
  $('empty').hidden = Boolean(rows.length);
}

api.storage.local.get({ status: [] }).then(({ status }) => showSessions(status));
api.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.status) showSessions(changes.status.newValue);
});
$('grant').addEventListener('click', async () => {
  const granted = await api.permissions.request({ origins: ['<all_urls>'] });
  $('access').textContent = granted ? 'Site access granted.' : 'Site access refused.';
});
