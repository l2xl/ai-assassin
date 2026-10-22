// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

const PING_MS = 20000;

/** Returns the WebSocket URL of the WebSurf bridge on the harness at `origin`. */
export function bridgeUrl(origin) {
  const url = new URL('/websurf', origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}

/**
 * Returns the socket opened to the harness of a session -- `config.origin`, introduced with its `config.token` -- answering its surf
 * requests through `handle` once welcomed; its `report` sends a page frame then and drops it before.
 */
export function openBridge(WebSocketImpl, config, handle, onStatus = () => {}) {
  const socket = new WebSocketImpl(bridgeUrl(config.origin));
  let welcomed = false;
  let pinger = null;
  const send = (frame) => { if (socket.readyState === 1) socket.send(JSON.stringify(frame)); };
  socket.report = (frame) => { if (welcomed) send(frame); };
  socket.onopen = () => {
    send({ type: 'hello', token: config.token, version: 3, agent: config.agent });
    pinger = setInterval(() => send({ type: 'ping' }), config.pingMs || PING_MS);
    onStatus('authenticating');
  };
  socket.onmessage = async (event) => {
    let frame;
    try { frame = JSON.parse(event.data); } catch { return; }
    if (frame.type === 'welcome') {
      welcomed = true;
      onStatus('connected');
    } else if (frame.type === 'ping') {
      send({ type: 'pong' });
    } else if (frame.type === 'surf') {
      const result = welcomed
        ? await Promise.resolve().then(() => handle(frame)).catch((e) => ({ ok: false, error: String((e && e.message) || e) }))
        : { ok: false, error: 'bridge not authenticated' };
      send({ type: 'result', ...result, id: frame.id });
    }
  };
  socket.onclose = () => {
    clearInterval(pinger);
    onStatus('disconnected');
  };
  return socket;
}
