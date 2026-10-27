// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Entry point: session check, login gate, navigation (#/chat, #/status). docs/plan/15 P2-01.

import { api, onUnauthorized } from "./api.js";
import { h, icon } from "./dom.js";
import { createChat } from "./views/chat.js";
import { createStatus } from "./views/status.js";

// Only what works is shown; Verlauf, Modell and Einstellungen come with their tickets.
const ROUTES = [
  { id: "chat", label: "Chat", icon: "chat", create: createChat },
  { id: "status", label: "Status", icon: "status", create: createStatus },
];

const $ = (id) => document.getElementById(id);
const views = new Map();
let current = null;

function routeId() {
  const id = location.hash.replace(/^#\/?/, "").split("/")[0];
  return ROUTES.some((r) => r.id === id) ? id : "chat";
}

function buildNav() {
  $("nav-links").replaceChildren(
    ...ROUTES.map((route) =>
      h("a", { href: `#/${route.id}`, "data-route": route.id }, icon(route.icon), h("span", { text: route.label })),
    ),
  );
}

function navigate() {
  const id = routeId();
  for (const link of $("nav-links").querySelectorAll("a")) {
    if (link.dataset.route === id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (current && current.id !== id) current.view.hide();
  if (!views.has(id)) {
    const route = ROUTES.find((r) => r.id === id);
    const view = route.create();
    $("view").append(view.el);
    views.set(id, view);
  }
  const view = views.get(id);
  current = { id, view };
  for (const [other, v] of views) v.el.hidden = other !== id;
  document.title = `m-agent – ${ROUTES.find((r) => r.id === id).label}`;
  view.show();
}

function showShell() {
  $("problem").hidden = true;
  $("login").hidden = true;
  $("shell").hidden = false;
  navigate();
}

function showLogin() {
  $("problem").hidden = true;
  $("login").hidden = false;
  if (current) current.view.hide();
  const name = $("login-form").elements.username;
  (name.value ? $("login-form").elements.password : name).focus();
}

function showProblem(title, text) {
  $("shell").hidden = true;
  $("login").hidden = true;
  $("problem-title").textContent = title;
  $("problem-text").textContent = text;
  $("problem").hidden = false;
}

async function start() {
  const session = await api("/api/session");
  if (!session.ok) {
    return showProblem("Anton antwortet nicht", "Der Dienst läuft gerade nicht oder startet noch. Versuch es gleich nochmal.");
  }
  if (!session.body.login_configured) {
    return showProblem(
      "Anmeldung noch nicht eingerichtet",
      "Trag in passwords.txt im Abschnitt [web_login] Benutzername und Passwort ein und lade die Konfiguration neu.",
    );
  }
  if (session.body.authenticated) showShell();
  else showLogin();
}

async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const error = $("login-error");
  error.textContent = "";
  button.disabled = true;
  const result = await api("/api/login", {
    method: "POST",
    body: { username: form.elements.username.value, password: form.elements.password.value },
  });
  button.disabled = false;
  if (result.ok) {
    form.elements.password.value = "";
    return showShell();
  }
  const detail = (result.body && result.body.detail) || {};
  if (result.status === 429) {
    error.textContent = `Zu viele Versuche. Warte ${detail.retry_after_s || 60} Sekunden.`;
  } else if (result.status === 401) {
    error.textContent = "Benutzername oder Passwort stimmt nicht.";
  } else {
    error.textContent = "Anmelden geht gerade nicht. Versuch es gleich nochmal.";
  }
}

async function logout() {
  await api("/api/logout", { method: "POST" });
  showLogin();
}

onUnauthorized(showLogin);
buildNav();
window.addEventListener("hashchange", () => { if (!$("shell").hidden) navigate(); });
$("login-form").addEventListener("submit", login);
$("logout").addEventListener("click", logout);
$("problem-retry").addEventListener("click", start);
start();
