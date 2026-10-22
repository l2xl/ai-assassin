// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

// The hosts an AI Assassin server is served on, as the URL parser writes them.
const LOOPBACK = ['127.0.0.1', 'localhost', '[::1]'];

/**
 * Returns `{origin, token}` of an AI Assassin tab's URL -- `http://<host>:<port>/?token=<t>`, the host a loopback literal, the path `/`
 * and the token not empty, as the page keeps it in its URL for its whole life -- else null; nothing but the URL is read.
 */
export function assassinSession(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const token = parsed.searchParams.get('token');
  if (parsed.protocol !== 'http:' || !LOOPBACK.includes(parsed.hostname) || parsed.pathname !== '/' || !token || parsed.username || parsed.password) return null;
  return { origin: parsed.origin, token };
}
