// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Chat with Anton over /api/chat (P2-01). Streaming, Markdown and the run timeline come with P2-02.

import { api } from "../api.js";
import { h, icon, safeUrl, store } from "../dom.js";

const MAX_CHARS = 4000;
const CONVERSATION_KEY = "m-agent.conversation";
const SUGGESTIONS = [
  "Wie wird das Wetter morgen?",
  "Was ist 17 mal 23?",
  "Wann ist der nächste Feiertag?",
  "Was ist der Sinn des Lebens?",
];

function newConversationId() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return "w-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function cardView(card, said) {
  const fields = (card.fields || []).map((f) =>
    h("div", { class: f.inline && String(f.value).length <= 40 ? "field" : "field wide" }, h("dt", { text: f.name }), h("dd", { text: f.value })),
  );
  const description = card.description && card.description.trim() !== said.trim() ? card.description : null;
  return h(
    "div",
    { class: `card ${card.color === "warn" ? "warn" : ""}` },
    card.title ? h("h3", { text: card.title }) : null,
    description ? h("div", { text: description }) : null,
    fields.length ? h("dl", {}, fields) : null,
    card.footer ? h("footer", { text: card.footer }) : null,
  );
}

function sourcesView(sources) {
  const items = [];
  for (const source of sources || []) {
    const href = safeUrl(source.url || "");
    const label = source.title || source.name || (href ? new URL(href).hostname : "");
    if (!label) continue;
    items.push(
      h("li", {}, href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: label }) : h("span", { text: label })),
    );
  }
  return items.length ? h("ul", { class: "sources", "aria-label": "Quellen" }, items) : null;
}

export function createChat() {
  let conversation = store.get(CONVERSATION_KEY) || newConversationId();
  let busy = false;

  const list = h("div", { class: "messages-inner", "aria-live": "polite" });
  const messages = h("div", { class: "messages" }, list);
  const input = h("textarea", {
    rows: 1,
    maxlength: MAX_CHARS,
    placeholder: "Frag Anton …",
    "aria-label": "Nachricht an Anton",
  });
  const send = h("button", { class: "primary", type: "submit", "aria-label": "Senden" }, icon("send"));
  const form = h("form", {}, input, send);
  const el = h(
    "section",
    { class: "chat" },
    h(
      "div",
      { class: "chat-top" },
      h("p", { class: "eyebrow" }, "Anton", h("span", { class: "sep", text: "/" }), "Chat"),
      h("button", { class: "ghost", type: "button", onclick: reset }, icon("plus"), " Neues Gespräch"),
    ),
    messages,
    h("div", { class: "composer" }, form, h("p", { class: "hint", text: "Enter sendet, Shift+Enter macht eine neue Zeile." })),
  );

  function empty() {
    list.replaceChildren(
      h(
        "div",
        { class: "empty" },
        h("img", { class: "mascot", src: "/branding/scribbles/scribbles-white.svg", height: 110, alt: "Scribbles" }),
        h("h1", { class: "headline" }, "Frag Anton", h("br"), h("span", { class: "accent", text: "alles." })),
        h(
          "div",
          { class: "suggestions" },
          SUGGESTIONS.map((text) => h("button", { type: "button", class: "secondary", text, onclick: () => ask(text) })),
        ),
      ),
    );
  }

  function scroll() {
    messages.scrollTop = messages.scrollHeight;
  }

  function add(node) {
    const placeholder = list.querySelector(".empty");
    if (placeholder) placeholder.remove();
    list.append(node);
    scroll();
    return node;
  }

  function userMessage(text) {
    return add(h("div", { class: "msg user" }, h("div", { class: "bubble", text })));
  }

  function antonMessage() {
    const bubble = h("div", { class: "bubble" }, h("span", { class: "typing", "aria-label": "Anton schreibt" }, h("i"), h("i"), h("i")));
    const row = add(h("div", { class: "msg anton" }, h("img", { class: "avatar", src: "/branding/m-agent-logo-64.png", alt: "Anton" }), bubble));
    return { row, bubble };
  }

  function chips(labelled) {
    const buttons = labelled.map(([label, say]) => h("button", { type: "button", class: "secondary", text: label, onclick: () => ask(say) }));
    return buttons.length ? h("div", { class: "chips" }, buttons) : null;
  }

  function fill(bubble, data) {
    const options = (data.clarify && data.clarify.options) || [];
    const actions = (data.actions || []).map((a) => [a.label, a.say]);
    const said = data.text || (data.clarify && data.clarify.question) || "…";
    const parts = [
      document.createTextNode(said),
      data.card ? cardView(data.card, said) : null,
      chips(options.map((o) => [o, o])),
      chips(actions),
      sourcesView(data.sources),
    ];
    bubble.replaceChildren(...parts.filter(Boolean));
  }

  function failed(row, bubble, text) {
    row.classList.add("failed");
    bubble.textContent = text;
  }

  async function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true;
    send.disabled = true;
    userMessage(text);
    const { row, bubble } = antonMessage();
    const result = await api("/api/chat", { method: "POST", body: { message: text, conversation_id: conversation } });
    busy = false;
    send.disabled = false;
    if (result.ok) {
      fill(bubble, result.body);
    } else if (result.status === 401) {
      row.remove();
      if (list.lastElementChild) list.lastElementChild.remove();
      if (!list.childElementCount) empty();
      input.value = text; // the login comes up; the question waits in the field
    } else if (result.status === 503) {
      failed(row, bubble, "Das Sprachmodell ist gerade nicht bereit. Sofortauskünfte wie Wetter oder Uhrzeit gehen trotzdem.");
    } else if (result.status === 0) {
      failed(row, bubble, "Keine Verbindung zu Anton.");
    } else {
      failed(row, bubble, `Da ist was schiefgelaufen (Fehler ${result.status}).`);
    }
    scroll();
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }

  function reset() {
    conversation = newConversationId();
    store.set(CONVERSATION_KEY, conversation);
    empty();
    input.focus();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value;
    input.value = "";
    autosize();
    ask(text);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", autosize);

  store.set(CONVERSATION_KEY, conversation);
  empty();
  return {
    el,
    show() { input.focus(); },
    hide() {},
  };
}
