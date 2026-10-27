// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// History of every channel (P2-04): search, filter, saved first, rename, save, export, delete.
// A web chat opens in the chat; calls and Discord open read-only here (#/verlauf/<id>).

import { api } from "../api.js";
import { h, icon } from "../dom.js";
import { storedMessage } from "../messages.js";

const SOURCES = {
  web: { label: "Web", icon: "globe" },
  phone: { label: "Telefon", icon: "phone" },
  discord: { label: "Discord", icon: "chat" },
  voice: { label: "Sprachkanal", icon: "voice" },
};
const FILTERS = [
  ["", "Alle"],
  ["web", "Web"],
  ["phone", "Telefon"],
  ["discord", "Discord"],
  ["voice", "Sprachkanal"],
  ["pinned", "Gespeichert"],
];
const DAY_MS = 86400000;

function when(seconds) {
  const date = new Date(seconds * 1000);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const time = date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (date >= today) return time;
  if (date >= new Date(today - DAY_MS)) return `gestern ${time}`;
  return date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) + ` ${time}`;
}

function group(seconds) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const ms = seconds * 1000;
  if (ms >= today) return "Heute";
  if (ms >= today - DAY_MS) return "Gestern";
  if (ms >= today - 6 * DAY_MS) return "Diese Woche";
  return "Älter";
}

export function createHistory() {
  let filter = "";
  let query = "";
  let timer = null;
  let detailId = null;

  const search = h("input", { type: "search", placeholder: "Verlauf durchsuchen …", "aria-label": "Verlauf durchsuchen" });
  const chips = h("div", { class: "filters", role: "group", "aria-label": "Filter" });
  const listBox = h("div", { class: "history-list" });
  const listPage = h(
    "section",
    { class: "page" },
    h("div", { class: "page-head" }, h("div", {}, h("p", { class: "eyebrow", text: "Web · Telefon · Discord" }), h("h1", { text: "Verlauf" }))),
    h("div", { class: "history-tools" }, search, chips),
    listBox,
    h("p", { class: "muted small", text: "Gespräche bleiben 15 Tage. Gespeicherte bleiben für immer." }),
  );
  const detail = h("section", { class: "page history-detail", hidden: true });
  const el = h("div", { class: "history" }, listPage, detail);

  function drawChips() {
    chips.replaceChildren(
      ...FILTERS.map(([value, label]) =>
        h("button", {
          type: "button",
          class: `chip ${filter === value ? "on" : ""}`,
          "aria-pressed": filter === value ? "true" : "false",
          text: label,
          onclick: () => { filter = value; drawChips(); load(); },
        }),
      ),
    );
  }

  async function load() {
    const params = new URLSearchParams({ limit: "200" });
    if (query) params.set("q", query);
    if (filter === "pinned") params.set("pinned", "true");
    else if (filter) params.set("source", filter);
    const result = await api(`/api/conversations?${params}`);
    if (!result.ok) {
      if (result.status !== 401) listBox.replaceChildren(h("p", { class: "error", text: "Der Verlauf ist gerade nicht lesbar." }));
      return;
    }
    draw(result.body.items);
  }

  function draw(items) {
    if (!items.length) {
      listBox.replaceChildren(
        h(
          "div",
          { class: "empty small-empty" },
          h("img", { class: "mascot", src: "/branding/scribbles/scribbles-white.svg", height: 80, alt: "" }),
          h("p", { class: "muted", text: query ? "Nichts gefunden." : "Noch keine Gespräche." }),
        ),
      );
      return;
    }
    const sections = new Map();
    for (const item of items) {
      const name = item.pinned ? "Gespeichert" : group(item.updated_at);
      if (!sections.has(name)) sections.set(name, []);
      sections.get(name).push(item);
    }
    const order = ["Gespeichert", "Heute", "Gestern", "Diese Woche", "Älter"];
    listBox.replaceChildren(
      ...order
        .filter((name) => sections.has(name))
        .map((name) => h("div", { class: "history-group" }, h("p", { class: "eyebrow", text: name }), h("ul", {}, sections.get(name).map(row)))),
    );
  }

  function row(item) {
    const source = SOURCES[item.source] || SOURCES.web;
    const title = h("span", { class: "history-title", text: item.title });
    const open = h(
      "a",
      { class: "history-open", href: item.chat_id ? `#/chat/${encodeURIComponent(item.chat_id)}` : `#/verlauf/${item.id}` },
      h("span", { class: `source ${item.source}`, title: source.label }, icon(source.icon)),
      h("span", { class: "history-text" }, title, h("span", { class: "muted small", text: item.snippet || "" })),
      h("span", { class: "muted small history-when", text: when(item.updated_at) }),
    );
    const pin = h("button", {
      type: "button",
      class: `icon-button ${item.pinned ? "on" : ""}`,
      title: item.pinned ? "Gespeichert – nicht mehr für immer behalten" : "Für immer behalten",
      "aria-label": item.pinned ? "Nicht mehr speichern" : "Speichern",
      onclick: async () => {
        const result = await api(`/api/conversations/${item.id}`, { method: "PATCH", body: { pinned: !item.pinned } });
        if (result.ok) load();
      },
    }, icon("pin"));
    const rename = h("button", { type: "button", class: "icon-button", title: "Umbenennen", "aria-label": "Umbenennen", onclick: () => editTitle(item, title) }, icon("edit"));
    const exportLink = h("a", { class: "icon-button", href: `/api/conversations/${item.id}/export.md`, title: "Als Markdown speichern", "aria-label": "Exportieren", download: "" }, icon("download"));
    const remove = h("button", {
      type: "button",
      class: "icon-button danger",
      title: "Löschen",
      "aria-label": "Löschen",
      onclick: async () => {
        if (!window.confirm(`„${item.title}“ löschen? Das geht nicht rückgängig.`)) return;
        const result = await api(`/api/conversations/${item.id}`, { method: "DELETE" });
        if (result.ok) load();
      },
    }, icon("trash"));
    return h("li", { class: `history-row ${item.pinned ? "pinned" : ""}` }, open, h("div", { class: "history-actions" }, pin, rename, exportLink, remove));
  }

  function editTitle(item, title) {
    const field = h("input", { value: item.title, maxlength: 200, "aria-label": "Neuer Titel" });
    const finish = async (save) => {
      const value = field.value.trim();
      field.replaceWith(title);
      if (save && value && value !== item.title) {
        const result = await api(`/api/conversations/${item.id}`, { method: "PATCH", body: { title: value } });
        if (result.ok) load();
      }
    };
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      if (event.key === "Escape") finish(false);
    });
    field.addEventListener("blur", () => finish(true), { once: true });
    field.addEventListener("click", (event) => event.preventDefault()); // it sits in the row's link
    title.replaceWith(field);
    field.focus();
    field.select();
  }

  async function showDetail(id) {
    detailId = id;
    listPage.hidden = true;
    detail.hidden = false;
    detail.replaceChildren(h("p", { class: "muted", text: "Lade …" }));
    const result = await api(`/api/conversations/${id}`);
    if (detailId !== id) return;
    if (!result.ok) {
      detail.replaceChildren(h("a", { href: "#/verlauf", class: "back", text: "← Verlauf" }), h("p", { class: "error", text: "Dieses Gespräch gibt es nicht mehr." }));
      return;
    }
    const data = result.body;
    const source = SOURCES[data.source] || SOURCES.web;
    const list = h("div", { class: "messages-inner" });
    for (const message of data.messages) storedMessage(list, message, () => {});
    detail.replaceChildren(
      h("a", { href: "#/verlauf", class: "back", text: "← Verlauf" }),
      h(
        "div",
        { class: "page-head" },
        h("div", {}, h("p", { class: "eyebrow", text: `${source.label} · ${when(data.created_at)}` }), h("h1", { text: data.title })),
        h("a", { class: "secondary button-link", href: `/api/conversations/${id}/export.md`, download: "" }, icon("download"), " Markdown"),
      ),
      list,
    );
  }

  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = search.value.trim(); load(); }, 250);
  });
  drawChips();

  return {
    el,
    show(args = []) {
      if (args[0]) return showDetail(args[0]);
      detailId = null;
      detail.hidden = true;
      listPage.hidden = false;
      load();
    },
    hide() {},
  };
}
