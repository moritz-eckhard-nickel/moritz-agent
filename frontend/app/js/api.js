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
