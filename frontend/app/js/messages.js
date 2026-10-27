// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// How Anton's answers look – live while a run streams (ADR-041) and later in the history (P2-04).

import { h, icon, safeUrl } from "./dom.js";
import { markdown } from "./markdown.js";

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
export class Answer {
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

// Moritz' message, with the files that came with it.
export function userMessage(text, files = []) {
  const chips = files.length
    ? h("div", { class: "file-chips" }, files.map((f) => h("a", { class: "file-chip", href: `/api/files/${f.id}`, download: "" }, icon("file"), h("span", { text: f.name }))))
    : null;
  return h("div", { class: "msg user" }, h("div", { class: "bubble-stack" }, chips, h("div", { class: "bubble", text })));
}

// A message from the history: the question as a bubble, an answer with its steps, card and sources.
export function storedMessage(list, message, onAsk) {
  if (message.role === "user") {
    const row = userMessage(message.text, (message.meta && message.meta.files) || []);
    list.append(row);
    return row;
  }
  const answer = new Answer(list, onAsk);
  for (const step of message.steps || []) {
    if (step.type === "tool_call" || step.type === "tool_result") answer.event(step);
  }
  const meta = message.meta || {};
  answer.done({ markdown: message.text, text: message.text, card: meta.card, sources: meta.sources || [] });
  return answer.row;
}
