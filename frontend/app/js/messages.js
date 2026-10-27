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
function seconds(ms) {
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}

const RISK = { read: "liest", write: "verändert etwas", execute: "führt etwas aus" };

export class Answer {
  constructor(list, onAsk, onApprove = null) {
    this.onAsk = onAsk;
    this.onApprove = onApprove;
    this.text = "";
    this.started = Date.now();
    this.steps = h("ol", { class: "steps" });
    this.summary = h("summary", {}, h("span", { text: "Schritte" }));
    this.timeline = h("details", { class: "timeline", open: true, hidden: true }, this.summary, this.steps);
    this.approvals = new Map();
    this.status = h("div", { class: "run-status" }, h("span", { class: "typing", "aria-label": "Anton schreibt" }, h("i"), h("i"), h("i")));
    this.body = h("div", { class: "answer" });
    this.extras = h("div", { class: "answer-extras" });
    this.bubble = h("div", { class: "bubble" }, this.timeline, this.body, this.status, this.extras);
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
        this.timeline.hidden = false;
        this.steps.append(item);
        this.pending.set(event.tool, item);
        break;
      }
      case "tool_output": {
        // a tool that streams (later: a shell in the sandbox) – shown like a console
        const item = this.pending.get(event.tool);
        if (!item) break;
        let consoleView = item.querySelector("pre.console");
        if (!consoleView) {
          consoleView = h("pre", { class: "console" });
          item.append(consoleView);
        }
        consoleView.textContent += event.text;
        consoleView.scrollTop = consoleView.scrollHeight;
        break;
      }
      case "tool_result": {
        const item = this.pending.get(event.tool);
        if (item) {
          item.classList.remove("running");
          item.classList.add(event.ok ? "ok" : "failed");
          item.insertBefore(h("span", { class: "muted", text: ` ${seconds(event.ms)}${event.error === "denied" ? " · nicht erlaubt" : ""}` }), item.querySelector("pre.console"));
          this.pending.delete(event.tool);
        }
        break;
      }
      case "approval_request":
        this.ask(event);
        break;
      case "approval_response": {
        const box = this.approvals.get(event.id);
        if (box) {
          const text = event.allow ? "Erlaubt." : event.by === "timeout" ? "Keine Antwort – nicht gemacht." : "Abgelehnt.";
          box.querySelector(".approval-actions").replaceChildren(h("span", { class: `note ${event.allow ? "" : "failed"}`, text }));
          box.classList.add("answered");
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

  // "Anton möchte … – Erlauben / Ablehnen" (ADR-041 Nr. 4)
  ask(event) {
    const args = Object.entries(event.args || {}).map(([key, value]) => h("div", {}, h("span", { class: "muted", text: `${key}: ` }), h("code", { text: value })));
    const decide = (allow) => async () => {
      for (const button of box.querySelectorAll("button")) button.disabled = true;
      if (this.onApprove) await this.onApprove(event.id, allow);
    };
    const actions = this.onApprove
      ? h("div", { class: "approval-actions" }, h("button", { type: "button", class: "primary", text: "Erlauben", onclick: decide(true) }), h("button", { type: "button", class: "secondary", text: "Ablehnen", onclick: decide(false) }))
      : h("div", { class: "approval-actions" });
    const box = h(
      "li",
      { class: "approval" },
      h("strong", { text: `Anton möchte ${TOOL_NAMES[event.tool] || event.tool} benutzen` }),
      h("span", { class: "muted small", text: ` – ${RISK[event.risk] || RISK.execute}` }),
      args.length ? h("div", { class: "approval-args" }, args) : null,
      actions,
    );
    this.approvals.set(event.id, box);
    this.timeline.hidden = false;
    this.timeline.open = true;
    this.steps.append(box);
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
    this.finish(result.stats);
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

  finish(stats = null) {
    this.over = true;
    this.status.remove();
    const count = this.steps.querySelectorAll(".step").length;
    if (this.steps.childElementCount) {
      const ms = (stats && stats.ms) || Date.now() - this.started;
      const dropped = stats && stats.dropped_turns ? ` · ${stats.dropped_turns} ältere Wechsel nicht mehr im Kontext` : "";
      const asked = this.approvals.size ? ` · ${this.approvals.size} Nachfrage${this.approvals.size === 1 ? "" : "n"}` : "";
      this.summary.replaceChildren(h("span", { text: `${count} ${count === 1 ? "Schritt" : "Schritte"}${asked} · ${seconds(ms)}${dropped}` }));
      this.timeline.open = false;
    }
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
    if (["tool_call", "tool_result", "approval_request", "approval_response"].includes(step.type)) answer.event(step);
  }
  const meta = message.meta || {};
  answer.done({ markdown: message.text, text: message.text, card: meta.card, sources: meta.sources || [], stats: meta.stats });
  return answer.row;
}
