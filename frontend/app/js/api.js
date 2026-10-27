// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// fetch with JSON; a 401 hands over to the login without throwing away the page.

let unauthorized = () => {};

export function onUnauthorized(handler) {
  unauthorized = handler;
}

export async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (_) {
    return { ok: false, status: 0, body: null };
  }
  let data = null;
  try { data = await response.json(); } catch (_) { /* no JSON body */ }
  if (response.status === 401 && path !== "/api/login") unauthorized();
  return { ok: response.ok, status: response.status, body: data };
}

// Server-Sent Events over fetch (POST is possible, EventSource cannot do that). Calls onEvent for
// every event and returns how the stream ended: {ok, status, last} – last = the seq of the last event.
export async function stream(path, { method = "GET", body, signal } = {}, onEvent) {
  let response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? { Accept: "text/event-stream" } : { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (_) {
    return { ok: false, status: 0, last: 0 };
  }
  if (response.status === 401) unauthorized();
  if (!response.ok || !response.body) {
    let data = null;
    try { data = await response.json(); } catch (_) { /* no JSON body */ }
    return { ok: false, status: response.status, last: 0, body: data };
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (!data) continue;
        const event = JSON.parse(data);
        last = event.seq || last;
        onEvent(event);
      }
    }
  } catch (_) {
    return { ok: false, status: response.status, last, broken: true };
  }
  return { ok: true, status: response.status, last };
}
