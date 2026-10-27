// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Chat with Anton: every answer is a run streamed live (ADR-041, P2-02). Text arrives word by word as
// Markdown, tool steps show up while they run, "Stopp" cancels, a broken connection follows the run again.

import { api, stream } from "../api.js";
import { h, icon, safeUrl, store } from "../dom.js";
import { markdown } from "../markdown.js";

const MAX_CHARS = 4000;
const CONVERSATION_KEY = "m-agent.conversation";
const SUGGESTIONS = [
  "Wie wird das Wetter morgen?",
  "Was ist 17 mal 23?",
  "Wann ist der nächste Feiertag?",
  "Was ist der Sinn des Lebens?",
];
const TOOL_NAMES = {
  get_current_time: "Uhrzeit",
  web_search: "Websuche",
  get_weather: "Wetter",
  get_warnings: "Unwetterwarnungen",
  get_pollen: "Pollenflug",
  get_air_quality: "Luftqualität",
  get_sun_moon: "Sonne und Mond",
  calendar_info: "Kalender",
  calculate: "Rechnen",
  money_info: "Geld und Kurse",
  regional_info: "Region",
  place_info: "Ort",
  everyday_advice: "Ratschlag",
};
const ERRORS = {
  model_unavailable: "Das Sprachmodell ist gerade nicht bereit. Sofortauskünfte wie Wetter oder Uhrzeit gehen trotzdem.",
  forbidden: "Das darfst du hier nicht.",
  no_answer: "Darauf kam keine Antwort.",
  internal: "Da ist was schiefgelaufen.",
};
const RETRIES = 3;

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
  // folded by default: the answer above says the essentials, the card holds the details
  return h(
    "details",
    { class: `card ${card.color === "warn" ? "warn" : ""}` },
    h("summary", {}, h("span", { text: card.title || "Details" }), h("span", { class: "muted", text: "Details" })),
    description ? h("div", { class: "card-text", text: description }) : null,
    fields.length ? h("dl", {}, fields) : null,
    card.footer ? h("footer", { text: card.footer }) : null,
  );
}

function sourcesView(sources) {
  const items = [];
  const seen = new Set();
  for (const source of sources || []) {
    const href = safeUrl(source.url || "");
    const label = source.title || source.name || (href ? new URL(href).hostname : "");
    if (!label || seen.has(href || label)) continue;
    seen.add(href || label);
    items.push(
      h("li", {}, href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: label }) : h("span", { text: label })),
    );
  }
  return items.length ? h("ul", { class: "sources", "aria-label": "Quellen" }, items) : null;
}

function toolLabel(event) {
  const name = TOOL_NAMES[event.tool] || event.tool;
  const args = event.args || {};
  const detail = args.query || args.question || args.place || args.expression || "";
  return detail ? `${name} „${detail}“` : name;
}

// One answer of Anton while it is made: steps, live text, then the final form.
class Answer {
  constructor(list, onAsk) {
    this.onAsk = onAsk;
    this.text = "";
    this.steps = h("ol", { class: "steps", hidden: true });
    this.status = h("div", { class: "run-status" }, h("span", { class: "typing", "aria-label": "Anton schreibt" }, h("i"), h("i"), h("i")));
    this.body = h("div", { class: "answer" });
    this.extras = h("div", { class: "answer-extras" });
    this.bubble = h("div", { class: "bubble" }, this.steps, this.body, this.status, this.extras);
    this.row = h("div", { class: "msg anton" }, h("img", { class: "avatar", src: "/branding/m-agent-logo-64.png", alt: "Anton" }), this.bubble);
    this.pending = new Map();
    this.frame = 0;
    this.over = false;
    list.append(this.row);
  }

  event(event) {
    switch (event.type) {
      case "status":
        if (event.text) this.statusText(event.text);
        break;
      case "tool_call": {
        const item = h("li", { class: "step running" }, h("span", { class: "step-dot" }), h("span", { text: toolLabel(event) }));
        this.steps.hidden = false;
        this.steps.append(item);
        this.pending.set(event.tool, item);
        break;
      }
      case "tool_result": {
        const item = this.pending.get(event.tool);
        if (item) {
          item.className = `step ${event.ok ? "ok" : "failed"}`;
          item.append(h("span", { class: "muted", text: ` ${(event.ms / 1000).toFixed(1).replace(".", ",")} s` }));
          this.pending.delete(event.tool);
        }
        break;
      }
      case "token":
        this.text += event.text;
        this.draw();
        break;
      case "text":
        this.text = event.text;
        this.draw();
        break;
      case "done":
        this.done(event.result);
        break;
      case "cancelled":
        this.end(null, "cancelled");
        break;
      case "error":
        this.end(ERRORS[event.error] || ERRORS.internal, "failed");
        break;
      default:
        break;
    }
  }

  statusText(text) {
    this.status.replaceChildren(h("span", { class: "typing" }, h("i"), h("i"), h("i")), h("span", { class: "muted", text }));
  }

  draw() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.body.replaceChildren(markdown(this.text));
    });
  }

  done(result) {
    const said = result.markdown || result.text || (result.clarify && result.clarify.question) || "…";
    this.stopDrawing();
    this.body.replaceChildren(markdown(said));
    const options = (result.clarify && result.clarify.options) || [];
    const actions = (result.actions || []).map((a) => [a.label, a.say]);
    this.extras.replaceChildren(
      ...[
        result.card ? cardView(result.card, result.text || said) : null,
        this.chips(options.map((o) => [o, o])),
        this.chips(actions),
        sourcesView(result.sources),
      ].filter(Boolean),
    );
    this.finish();
  }

  end(message, kind) {
    this.stopDrawing();
    if (this.text) this.body.replaceChildren(markdown(this.text));
    const note = message || (kind === "cancelled" ? "Abgebrochen." : "");
    if (note) this.extras.replaceChildren(h("p", { class: `note ${kind}`, text: note }));
    this.finish();
  }

  stopDrawing() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  finish() {
    this.over = true;
    this.status.remove();
    for (const item of this.pending.values()) item.className = "step failed";
    this.pending.clear();
  }

  chips(labelled) {
    const buttons = labelled.map(([label, say]) => h("button", { type: "button", class: "secondary", text: label, onclick: () => this.onAsk(say) }));
    return buttons.length ? h("div", { class: "chips" }, buttons) : null;
  }
}

export function createChat() {
  let conversation = store.get(CONVERSATION_KEY) || newConversationId();
  let run = null; // {id, answer, last}

  const list = h("div", { class: "messages-inner", "aria-live": "polite" });
  const messages = h("div", { class: "messages" }, list);
  const input = h("textarea", { rows: 1, maxlength: MAX_CHARS, placeholder: "Frag Anton …", "aria-label": "Nachricht an Anton" });
  const send = h("button", { class: "primary", type: "submit", "aria-label": "Senden" }, icon("send"));
  const stop = h("button", { class: "secondary stop", type: "button", "aria-label": "Antwort stoppen", hidden: true, onclick: cancel }, icon("stop"));
  const form = h("form", {}, input, stop, send);
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
    const question = h("div", { class: "msg user" }, h("div", { class: "bubble", text }));
    list.append(question);
    run = { id: null, last: 0, answer: new Answer(list, ask) };
    const answer = run.answer;
    busy(true);
    scroll(true);
    let result = await follow("/api/chat/stream", { method: "POST", body: { message: text, conversation_id: conversation } });
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
    empty();
    input.focus();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (run) return;
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
