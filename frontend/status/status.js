// SPDX-License-Identifier: LicenseRef-MSOL-1.1
"use strict";

const LABELS = { ready: "bereit", starting: "startet", degraded: "eingeschränkt", failed: "gestört", disabled: "aus" };
const NAMES = {
  phone: "Telefon", inference: "Sprachmodell", search: "Websuche", skills: "Sofortauskünfte",
  agent: "Agent", storage: "Datenbank", config: "Konfiguration",
};
const ORDER = ["phone", "inference", "search", "skills", "agent", "storage", "config"];
const $ = (id) => document.getElementById(id);
let timer = null;

function show(view) {
  for (const id of ["login-view", "status-view", "error-view"]) $(id).hidden = id !== view;
  $("logout").hidden = view !== "status-view";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await response.json(); } catch (_) { /* no body */ }
  return { ok: response.ok, status: response.status, body };
}

function card(name, component) {
  const box = document.createElement("div");
  box.className = "card";
  const title = document.createElement("h3");
  const label = document.createElement("span");
  label.textContent = NAMES[name] || name;
  const badge = document.createElement("span");
  badge.className = "badge " + component.state;
  badge.textContent = LABELS[component.state] || component.state;
  title.append(label, badge);
  const text = document.createElement("p");
  text.textContent = component.message || "";
  box.append(title, text);
  return box;
}

function render(status) {
  const components = { ...status.components, phone: status.phone };
  const grid = $("components");
  grid.replaceChildren();
  const states = [];
  for (const name of ORDER) {
    if (!components[name]) continue;
    grid.append(card(name, components[name]));
    states.push(components[name].state);
  }
  const bad = states.filter((s) => s === "failed").length;
  const weak = states.filter((s) => s === "degraded" || s === "starting").length;
  $("banner-title").textContent = bad ? "Es gibt Störungen" : weak ? "Läuft mit Einschränkungen" : "Alles läuft";
  const uptime = Math.round((status.uptime_s || 0) / 60);
  $("banner-sub").textContent = `Version ${status.version}, läuft seit ${uptime} Min.` + (status.draining ? " – Wartungsmodus: keine neuen Anrufe" : "");
}

async function refresh() {
  const result = await api("/api/system/status");
  if (result.status === 401) return start();
  if (!result.ok) {
    $("banner-title").textContent = "Status nicht lesbar";
    return;
  }
  render(result.body);
}

async function start() {
  clearInterval(timer);
  const session = await api("/api/session");
  if (!session.ok) {
    $("error-text").textContent = "Der Dienst antwortet nicht. Bitte gleich noch einmal versuchen.";
    return show("error-view");
  }
  if (!session.body.login_configured) {
    $("error-title").textContent = "Anmeldung noch nicht eingerichtet";
    $("error-text").textContent = "In passwords.txt ist im Abschnitt [web_login] noch kein Benutzer eingetragen. Danach die Konfiguration neu laden.";
    return show("error-view");
  }
  if (!session.body.authenticated) return show("login-view");
  show("status-view");
  await refresh();
  timer = setInterval(refresh, 5000);
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  $("login-error").textContent = "";
  const result = await api("/api/login", {
    method: "POST",
    body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
  });
  if (result.ok) {
    event.target.reset();
    return start();
  }
  const detail = (result.body && result.body.detail) || {};
  $("login-error").textContent = result.status === 429
    ? `Zu viele Versuche. Bitte in ${Math.ceil((detail.retry_after_s || 60) / 60)} Min. noch einmal.`
    : "Benutzername oder Passwort stimmt nicht.";
});

$("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  start();
});

$("reload").addEventListener("click", async () => {
  $("reload-result").textContent = "Lade neu …";
  const result = await api("/api/system/reload", { method: "POST" });
  if (!result.ok) {
    $("reload-result").textContent = "Nicht möglich.";
  } else if (!result.body.ok) {
    $("reload-result").textContent = "Abgelehnt, der alte Stand bleibt aktiv: " + result.body.errors.join("; ");
  } else {
    const restart = result.body.restart_required.length ? ` (Neustart nötig für: ${result.body.restart_required.join(", ")})` : "";
    $("reload-result").textContent = (result.body.changed.length ? "Übernommen." : "Keine Änderung.") + restart;
  }
  refresh();
});

$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("chat-input");
  const answer = $("chat-answer");
  answer.textContent = "Anton denkt nach …";
  const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: input.value }) });
  answer.replaceChildren();
  if (!result.ok) {
    answer.textContent = result.status === 503 ? "Das Sprachmodell ist gerade nicht erreichbar." : "Das hat nicht geklappt.";
    return;
  }
  answer.append(document.createTextNode(result.body.text || result.body.prompt || ""));
  for (const source of result.body.sources || []) {
    const line = document.createElement("span");
    line.className = "src";
    line.textContent = "Quelle: " + source.name;
    answer.append(line);
  }
  input.value = "";
});

start();
