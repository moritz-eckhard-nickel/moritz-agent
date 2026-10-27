// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// System status (UI-01): every component, polled while the view is open. Live events come with P2-07.

import { api } from "../api.js";
import { h } from "../dom.js";

const LABELS = { ready: "bereit", starting: "startet", degraded: "eingeschränkt", failed: "gestört", disabled: "aus" };
const NAMES = {
  phone: "Telefon", discord: "Discord", inference: "Sprachmodell", search: "Websuche", skills: "Sofortauskünfte",
  agent: "Agent", storage: "Datenbank", config: "Konfiguration", web: "Weboberfläche",
};
const ORDER = Object.keys(NAMES);
const POLL_MS = 3000;

function tile(name, component) {
  return h(
    "div",
    { class: "tile" },
    h("h3", {}, h("span", { text: NAMES[name] || name }), h("span", { class: `badge ${component.state}`, text: LABELS[component.state] || component.state })),
    h("p", { text: component.message || "" }),
  );
}

export function createStatus() {
  let timer = null;
  const title = h("strong", { text: "Lade …" });
  const sub = h("div", { class: "muted" });
  const grid = h("div", { class: "grid" });
  const reloadResult = h("span", { class: "muted", role: "status" });
  const reload = h("button", { class: "secondary", type: "button", text: "Konfiguration neu laden", onclick: reloadConfig });
  const el = h(
    "section",
    { class: "page" },
    h("div", { class: "page-head" }, h("div", {}, h("p", { class: "eyebrow", text: "System" }), h("h1", { text: "Status" }))),
    h(
      "div",
      { class: "banner", role: "status" },
      h("img", { src: "/branding/scribbles/scribbles-white.svg", height: 56, alt: "" }),
      h("div", {}, title, sub),
    ),
    grid,
    h("div", { class: "actions" }, reload, reloadResult),
  );

  function render(status) {
    const components = { ...(status.components || {}), phone: status.phone };
    const names = [...ORDER.filter((n) => components[n]), ...Object.keys(components).filter((n) => !ORDER.includes(n))];
    const states = names.map((n) => components[n] && components[n].state);
    grid.replaceChildren(...names.filter((n) => components[n]).map((n) => tile(n, components[n])));
    const bad = states.filter((s) => s === "failed").length;
    const weak = states.filter((s) => s === "degraded" || s === "starting").length;
    title.textContent = bad ? "Es gibt Störungen" : weak ? "Läuft mit Einschränkungen" : "Alles läuft";
    const minutes = Math.round((status.uptime_s || 0) / 60);
    sub.textContent = `Version ${status.version}, läuft seit ${minutes} Min.` + (status.draining ? " – Wartungsmodus: keine neuen Anrufe" : "");
  }

  async function refresh() {
    const result = await api("/api/system/status");
    if (result.ok) render(result.body);
    else if (result.status !== 401) title.textContent = "Status nicht lesbar";
  }

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
    refresh();
  }

  return {
    el,
    show() {
      refresh();
      clearInterval(timer);
      timer = setInterval(refresh, POLL_MS);
    },
    hide() {
      clearInterval(timer);
      timer = null;
    },
  };
}
