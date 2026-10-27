// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Chat with Anton: every answer is a run streamed live (ADR-041, P2-02). Text arrives word by word as
// Markdown, tool steps show up while they run, "Stopp" cancels, a broken connection follows the run again.

import { api, stream, upload } from "../api.js";
import { h, icon, store } from "../dom.js";
import { Answer, storedMessage, userMessage } from "../messages.js";

const MAX_CHARS = 4000;
const CONVERSATION_KEY = "m-agent.conversation";
const SUGGESTIONS = [
  "Wie wird das Wetter morgen?",
  "Was ist 17 mal 23?",
  "Wann ist der nächste Feiertag?",
  "Was ist der Sinn des Lebens?",
];
const RETRIES = 3;
const MAX_FILES = 5;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const ACCEPT = ".pdf,.txt,.md,.csv,.tsv,.json,.jsonl,.log,.xml,.yaml,.yml,.toml,.ini,.cfg,.conf,.py,.js,.ts,.html,.css,.sh,.c,.h,.cpp,.java,.go,.rs,.sql,.tex,.srt";

function size(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

function newConversationId() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return "w-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function createChat() {
  let conversation = store.get(CONVERSATION_KEY) || newConversationId();
  let run = null; // {id, answer, last}
  let saved = { id: null, pinned: false }; // this chat in the history (P2-04)
  let loading = null;
  let attached = []; // files of the next message: {file, id, state, note, el}

  const list = h("div", { class: "messages-inner", "aria-live": "polite" });
  const messages = h("div", { class: "messages" }, list);
  const input = h("textarea", { rows: 1, maxlength: MAX_CHARS, placeholder: "Frag Anton …", "aria-label": "Nachricht an Anton" });
  const send = h("button", { class: "primary", type: "submit", "aria-label": "Senden" }, icon("send"));
  const stop = h("button", { class: "secondary stop", type: "button", "aria-label": "Antwort stoppen", hidden: true, onclick: cancel }, icon("stop"));
  const picker = h("input", { type: "file", multiple: true, accept: ACCEPT, hidden: true });
  const clip = h("button", { class: "ghost clip", type: "button", title: "Datei anhängen (Text, PDF)", "aria-label": "Datei anhängen", onclick: () => picker.click() }, icon("clip"));
  const tray = h("div", { class: "attachments", hidden: true });
  const form = h("form", {}, clip, input, stop, send, picker);
  const pin = h("button", { class: "ghost pin", type: "button", disabled: true, title: "Gespräch für immer behalten", onclick: togglePin }, icon("pin"), h("span", { class: "label", text: "Speichern" }));
  const el = h(
    "section",
    { class: "chat" },
    h(
      "div",
      { class: "chat-top" },
      h("p", { class: "eyebrow" }, "Anton", h("span", { class: "sep", text: "/" }), "Chat"),
      h("div", { class: "chat-actions" }, pin, h("button", { class: "ghost", type: "button", onclick: reset }, icon("plus"), h("span", { class: "label", text: "Neues Gespräch" }))),
    ),
    messages,
    h("div", { class: "composer" }, tray, form, h("p", { class: "hint", text: "Enter sendet, Shift+Enter macht eine neue Zeile. Text und PDF hierher ziehen." })),
  );

  function empty() {
    list.replaceChildren(
      h(
        "div",
        { class: "empty" },
        h("img", { class: "mascot", src: "/branding/scribbles/scribbles-white.svg", height: 110, alt: "Scribbles" }),
        h("h1", { class: "headline" }, "Frag Anton", h("br"), h("span", { class: "accent", text: "alles." })),
        h("div", { class: "suggestions" }, SUGGESTIONS.map((text) => h("button", { type: "button", class: "secondary", text, onclick: () => ask(text) }))),
      ),
    );
  }

  function nearBottom() {
    return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
  }

  function scroll(force = false) {
    if (force || nearBottom()) messages.scrollTop = messages.scrollHeight;
  }

  function busy(on) {
    stop.hidden = !on;
    send.hidden = on;
  }

  async function follow(path, options) {
    const current = run;
    const result = await stream(path, options, (event) => {
      if (event.type === "run") current.id = event.run_id;
      current.answer.event(event);
      scroll();
    });
    current.last = Math.max(current.last, result.last);
    return result;
  }

  async function ask(text) {
    text = text.trim();
    if (!text || run) return;
    const placeholder = list.querySelector(".empty");
    if (placeholder) placeholder.remove();
    const files = attached.filter((a) => a.state === "ready").map((a) => ({ id: a.id, name: a.file.name }));
    clearTray();
    const question = userMessage(text, files);
    list.append(question);
    run = { id: null, last: 0, answer: null };
    const current = run;
    run.answer = new Answer(list, ask, (id, allow) =>
      api(`/api/runs/${current.id}/approval`, { method: "POST", body: { id, allow } }),
    );
    const answer = run.answer;
    busy(true);
    scroll(true);
    let result = await follow("/api/chat/stream", {
      method: "POST",
      body: { message: text, conversation_id: conversation, files: files.map((f) => f.id) },
    });
    // the connection broke while the run goes on in the server: follow it again
    for (let attempt = 0; !answer.over && result.broken && run.id && attempt < RETRIES; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 800 * (attempt + 1)));
      result = await follow(`/api/runs/${run.id}/events?after=${run.last}`, {});
    }
    if (result.status === 401) {
      question.remove();
      answer.row.remove();
      if (!list.childElementCount) empty();
      input.value = text; // the login comes up; the question waits in the field
    } else if (!answer.over) {
      if (result.status === 409) answer.end("Anton antwortet noch auf die letzte Frage.", "failed");
      else if (result.status === 0) answer.end("Keine Verbindung zu Anton.", "failed");
      else if (result.ok || result.broken) answer.end("Die Verbindung ist abgerissen.", "failed");
      else answer.end(`Da ist was schiefgelaufen (Fehler ${result.status}).`, "failed");
    }
    run = null;
    busy(false);
    scroll();
    lookup();
  }

  // -- the history (P2-04) -----------------------------------------------------------------------
  function showPin() {
    pin.disabled = !saved.id;
    pin.classList.toggle("on", saved.pinned);
    pin.querySelector(".label").textContent = saved.pinned ? "Gespeichert" : "Speichern";
    pin.title = saved.pinned ? "Gespeichert – wird nie automatisch gelöscht" : "Gespräch für immer behalten";
  }

  async function lookup() {
    const result = await api(`/api/conversations?chat=${encodeURIComponent(conversation)}&limit=1`);
    const item = result.ok && result.body.items[0];
    saved = item ? { id: item.id, pinned: item.pinned } : { id: null, pinned: false };
    showPin();
    return item || null;
  }

  async function togglePin() {
    if (!saved.id) return;
    const result = await api(`/api/conversations/${saved.id}`, { method: "PATCH", body: { pinned: !saved.pinned } });
    if (result.ok) saved = { id: result.body.id, pinned: result.body.pinned };
    showPin();
  }

  // Open a chat of the WebUI with everything said so far (from the history or after a reload).
  async function open(chatId) {
    if (run) return;
    conversation = chatId;
    store.set(CONVERSATION_KEY, conversation);
    empty();
    const item = await lookup();
    if (!item || conversation !== chatId) return;
    const result = await api(`/api/conversations/${item.id}`);
    if (!result.ok || conversation !== chatId || run) return;
    list.replaceChildren();
    for (const message of result.body.messages) storedMessage(list, message, ask);
    if (!list.childElementCount) empty();
    scroll(true);
  }

  async function cancel() {
    if (run && run.id) await api(`/api/runs/${run.id}/cancel`, { method: "POST" });
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }

  function reset() {
    if (run) return;
    conversation = newConversationId();
    store.set(CONVERSATION_KEY, conversation);
    saved = { id: null, pinned: false };
    showPin();
    clearTray();
    empty();
    if (location.hash.startsWith("#/chat/")) history.replaceState(null, "", "#/chat");
    input.focus();
  }

  // -- files (P2-05) ---------------------------------------------------------------------------------
  function drawTray() {
    tray.hidden = !attached.length;
    tray.replaceChildren(
      ...attached.map((item) => {
        const remove = h("button", { type: "button", class: "icon-button", "aria-label": `${item.file.name} entfernen`, onclick: () => detach(item) }, icon("close"));
        const note = item.state === "uploading" ? "lädt …" : item.state === "error" ? item.note : item.note || size(item.file.size);
        return h("div", { class: `file-chip ${item.state}` }, icon("file"), h("span", { class: "file-name", text: item.file.name }), h("span", { class: "muted small", text: note }), remove);
      }),
    );
  }

  function clearTray() {
    attached = [];
    drawTray();
  }

  async function attach(files) {
    for (const file of files) {
      if (attached.length >= MAX_FILES) break;
      const item = { file, id: null, state: "uploading", note: "" };
      attached.push(item);
      if (file.size > MAX_FILE_BYTES) {
        Object.assign(item, { state: "error", note: "größer als 10 MB" });
        continue;
      }
      drawTray();
      const result = await upload(`/api/files?chat=${encodeURIComponent(conversation)}&name=${encodeURIComponent(file.name)}`, file);
      if (!attached.includes(item)) continue; // removed meanwhile
      if (result.ok) {
        const info = result.body;
        const pages = info.pages ? `${info.pages} S., ` : "";
        Object.assign(item, { id: info.id, state: "ready", note: `${pages}${size(info.size)}${info.truncated ? ", gekürzt" : ""}` });
      } else {
        const detail = (result.body && result.body.detail) || {};
        Object.assign(item, { state: "error", note: detail.message || "geht nicht" });
      }
    }
    drawTray();
  }

  function detach(item) {
    attached = attached.filter((a) => a !== item);
    if (item.id) api(`/api/files/${item.id}`, { method: "DELETE" });
    drawTray();
  }

  picker.addEventListener("change", () => {
    attach([...picker.files]);
    picker.value = "";
  });
  el.addEventListener("dragover", (event) => {
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    el.classList.add("dropping");
  });
  el.addEventListener("dragleave", (event) => {
    if (!el.contains(event.relatedTarget)) el.classList.remove("dropping");
  });
  el.addEventListener("drop", (event) => {
    event.preventDefault();
    el.classList.remove("dropping");
    if (event.dataTransfer.files.length) attach([...event.dataTransfer.files]);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (run || attached.some((a) => a.state === "uploading")) return;
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
  loading = open(conversation);
  return {
    el,
    async show(args = []) {
      if (args[0] && args[0] !== conversation) {
        await loading;
        loading = open(args[0]);
      }
      input.focus();
    },
    hide() {},
  };
}
