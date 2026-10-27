// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// System status, live (UI-01, P2-07): the server sends a new picture when something changes
// (/api/events). Calls and the voice channel show up as they happen; the log can be opened below.

import { api } from "../api.js";
import { h } from "../dom.js";

const LABELS = { ready: "bereit", starting: "startet", degraded: "eingeschränkt", failed: "gestört", disabled: "aus" };
const NAMES = {
  phone: "Telefon", discord: "Discord", inference: "Sprachmodell", search: "Websuche", skills: "Sofortauskünfte",
  agent: "Agent", storage: "Datenbank", config: "Konfiguration", web: "Weboberfläche",
};
const ORDER = Object.keys(NAMES);
const CATEGORIES = [["", "Alle"], ["phone", "Telefon"], ["agent", "Agent"], ["discord", "Discord"], ["search", "Suche"], ["system", "System"]];
const LOG_MS = 4000;

function tile(name, component) {
  const detail = component.detail || {};
  const live = name === "phone" && detail.in_call ? h("span", { class: "live-dot", title: "Gespräch läuft" }) : null;
  return h(
    "div",
    { class: `tile ${live ? "live" : ""}` },
    h("h3", {}, h("span", {}, live, NAMES[name] || name), h("span", { class: `badge ${component.state}`, text: LABELS[component.state] || component.state })),
    h("p", { text: component.message || "" }),
  );
}

export function createStatus() {
  let source = null;
  let logTimer = null;
  let category = "";
  const title = h("strong", { text: "Lade …" });
  const sub = h("div", { class: "muted" });
  const liveBadge = h("span", { class: "muted small", text: "" });
  const grid = h("div", { class: "grid" });
  const reloadResult = h("span", { class: "muted", role: "status" });
  const reload = h("button", { class: "secondary", type: "button", text: "Konfiguration neu laden", onclick: reloadConfig });
  const logBox = h("pre", { class: "console log-view", text: "" });
  const logFilters = h("div", { class: "filters" });
  const logPanel = h("details", { class: "log-panel" }, h("summary", { text: "Logs" }), logFilters, logBox);
  const el = h(
    "section",
    { class: "page" },
    h("div", { class: "page-head" }, h("div", {}, h("p", { class: "eyebrow", text: "System" }), h("h1", { text: "Status" })), liveBadge),
    h(
      "div",
      { class: "banner", role: "status" },
      h("img", { src: "/branding/scribbles/scribbles-white.svg", height: 56, alt: "" }),
      h("div", {}, title, sub),
    ),
    grid,
    h("div", { class: "actions" }, reload, reloadResult),
    logPanel,
  );

  function render(status) {
    const components = { ...(status.components || {}), phone: status.phone };
    const names = [...ORDER.filter((n) => components[n]), ...Object.keys(components).filter((n) => !ORDER.includes(n))];
    const states = names.map((n) => components[n] && components[n].state);
    grid.replaceChildren(...names.filter((n) => components[n]).map((n) => tile(n, components[n])));
    const bad = states.filter((s) => s === "failed").length;
    const weak = states.filter((s) => s === "degraded" || s === "starting").length;
    const inCall = status.active_calls > 0 || (status.phone && status.phone.detail && status.phone.detail.in_call);
    title.textContent = inCall ? "Anton telefoniert gerade" : bad ? "Es gibt Störungen" : weak ? "Läuft mit Einschränkungen" : "Alles läuft";
    const minutes = Math.round((status.uptime_s || 0) / 60);
    sub.textContent = `Version ${status.version}, läuft seit ${minutes} Min.` + (status.draining ? " – Wartungsmodus: keine neuen Anrufe" : "") + (status.generating ? " – das Sprachmodell schreibt" : "");
  }

  function connect() {
    disconnect();
    source = new EventSource("/api/events");
    source.addEventListener("status", (event) => {
      liveBadge.textContent = "live";
      liveBadge.className = "live-badge";
      render(JSON.parse(event.data));
    });
    source.onerror = async () => {
      liveBadge.textContent = "verbindet neu …";
      liveBadge.className = "muted small";
      const check = await api("/api/system/status"); // a 401 brings the login up
      if (check.status === 401) disconnect();
      else if (check.ok) render(check.body);
    };
  }

  function disconnect() {
    if (source) source.close();
    source = null;
  }

  function drawFilters() {
    logFilters.replaceChildren(
      ...CATEGORIES.map(([value, label]) =>
        h("button", { type: "button", class: `chip ${category === value ? "on" : ""}`, text: label, onclick: () => { category = value; drawFilters(); loadLogs(); } }),
      ),
    );
  }

  async function loadLogs() {
    const result = await api(`/api/system/logs?lines=200${category ? `&category=${category}` : ""}`);
    if (!result.ok) return;
    const atEnd = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;
    logBox.textContent = result.body.lines.join("\n") || "Noch keine Einträge.";
    if (atEnd) logBox.scrollTop = logBox.scrollHeight;
  }

  logPanel.addEventListener("toggle", () => {
    clearInterval(logTimer);
    if (logPanel.open) {
      loadLogs();
      logTimer = setInterval(loadLogs, LOG_MS);
    }
  });

  async function reloadConfig() {
    reloadResult.textContent = "Lade neu …";
    const result = await api("/api/system/reload", { method: "POST" });
    if (!result.ok) {
      reloadResult.textContent = "Nicht möglich.";
    } else if (!result.body.ok) {
      reloadResult.textContent = "Abgelehnt, der alte Stand bleibt aktiv: " + result.body.errors.join("; ");
    } else {
      const restart = result.body.restart_required.length ? ` Neustart nötig für: ${result.body.restart_required.join(", ")}.` : "";
      reloadResult.textContent = (result.body.changed.length ? "Übernommen." : "Keine Änderung.") + restart;
    }
  }

  drawFilters();
  return {
    el,
    show() {
      connect();
      if (logPanel.open) {
        loadLogs();
        clearInterval(logTimer);
        logTimer = setInterval(loadLogs, LOG_MS);
      }
    },
    hide() {
      disconnect();
      clearInterval(logTimer);
    },
  };
}
