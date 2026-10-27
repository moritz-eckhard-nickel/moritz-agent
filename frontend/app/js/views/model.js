// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Model page (P2-08): one model (F-44) – its state, VRAM, speed, context and --moecpu, restart, measure.
// During a call restart and measuring are locked: the phone comes first.

import { api } from "../api.js";
import { h } from "../dom.js";

const LABELS = { ready: "bereit", starting: "lädt", degraded: "eingeschränkt", failed: "gestört", disabled: "aus" };
const KV = { f16: ["16 Bit", 2 * 48 * 4 * 128 * 2], q8_0: ["8 Bit", 2 * 48 * 4 * 128 * 1.0625], q4_0: ["4 Bit", 2 * 48 * 4 * 128 * 0.5625] };
const CONTEXTS = [8192, 16384, 32768, 51200, 65536, 98304, 131072];
const REFRESH_MS = 5000;

function gb(bytes) {
  return `${(bytes / 1024 ** 3).toFixed(1).replace(".", ",")} GB`;
}

function stat(label, value, hint = "") {
  return h("div", { class: "tile stat" }, h("p", { class: "eyebrow", text: label }), h("strong", { text: value }), hint ? h("p", { class: "muted small", text: hint }) : null);
}

export function createModel() {
  let timer = null;
  let data = null;
  const title = h("h1", { text: "Sprachmodell" });
  const stats = h("div", { class: "grid stats" });
  const context = h("select", { "aria-label": "Kontext" }, CONTEXTS.map((n) => h("option", { value: n, text: `${n.toLocaleString("de-DE")} Tokens` })));
  const kv = h("select", { "aria-label": "Speicher für den Kontext" }, Object.entries(KV).map(([value, [label]]) => h("option", { value, text: label })));
  const smart = h("input", { type: "number", min: 0, max: 8, step: 1, "aria-label": "Gesprächsstände im RAM" });
  const moecpu = h("input", { type: "number", min: 0, max: 48, step: 1, "aria-label": "MoE-Schichten auf der CPU" });
  const estimate = h("p", { class: "muted small" });
  const saveNote = h("span", { class: "muted", role: "status" });
  const restartButton = h("button", { type: "button", class: "secondary", text: "KoboldCpp neu starten", onclick: restart });
  const measureButton = h("button", { type: "button", class: "secondary", text: "Geschwindigkeit messen", onclick: measure });
  const measureNote = h("span", { class: "muted", role: "status" });
  const form = h(
    "form",
    { class: "settings-form" },
    h("label", {}, "Kontext", context),
    h("label", {}, "Speicher für den Kontext (KV-Cache)", kv),
    h("label", {}, "Gesprächsstände im RAM (Smart-Cache)", smart),
    h("label", {}, "MoE-Schichten im RAM (--moecpu)", moecpu),
    estimate,
    h("div", { class: "actions" }, h("button", { type: "submit", class: "primary", text: "Speichern" }), saveNote),
  );
  const el = h(
    "section",
    { class: "page" },
    h("div", { class: "page-head" }, h("div", {}, h("p", { class: "eyebrow", text: "Sprachmodell" }), title)),
    stats,
    h("h2", { class: "section-title", text: "Einstellungen" }),
    h("p", { class: "muted small", text: "Mehr Kontext braucht mehr Grafikspeicher; dann wandern mehr Modellteile in den RAM und Anton schreibt langsamer. Telefon und Sprachkanal nutzen davon immer nur einen kleinen Teil." }),
    form,
    h("h2", { class: "section-title", text: "Neustart und Messen" }),
    h("div", { class: "actions" }, restartButton, measureButton, measureNote),
  );

  function updateEstimate() {
    const tokens = Number(context.value);
    const perToken = KV[kv.value][1];
    estimate.textContent = `Der Kontext braucht etwa ${gb(tokens * perToken)} Grafikspeicher (geschätzt).`;
  }

  function render(model) {
    data = model;
    title.textContent = model.model || "Sprachmodell";
    const gpu = model.gpu;
    stats.replaceChildren(
      stat("Zustand", LABELS[model.state] || model.state, model.message),
      stat("Geschwindigkeit", model.tokens_per_s ? `${String(model.tokens_per_s).replace(".", ",")} Tokens/s` : "–", "letzte Antwort"),
      stat("Grafikspeicher", gpu ? `${(gpu.vram_used_mb / 1024).toFixed(1).replace(".", ",")} / ${(gpu.vram_total_mb / 1024).toFixed(1).replace(".", ",")} GB` : "–", gpu ? gpu.name : "keine NVIDIA-GPU gefunden"),
      stat("Kontext", `${model.settings.context_size.toLocaleString("de-DE")} Tokens`, `Telefon: ${model.settings.phone_context_tokens.toLocaleString("de-DE")}`),
    );
    const locked = model.in_call ? "Während eines Anrufs gesperrt." : "";
    restartButton.disabled = !model.managed || model.in_call;
    measureButton.disabled = model.state !== "ready" || model.in_call;
    restartButton.title = !model.managed ? "KoboldCpp wird hier nicht von moritz-agent gestartet." : locked;
    measureButton.title = locked;
    if (document.activeElement && form.contains(document.activeElement)) return; // do not overwrite while typing
    if (![...context.options].some((o) => Number(o.value) === model.settings.context_size)) {
      context.append(h("option", { value: model.settings.context_size, text: `${model.settings.context_size.toLocaleString("de-DE")} Tokens` }));
    }
    context.value = String(model.settings.context_size);
    kv.value = model.settings.kv_cache;
    smart.value = String(model.settings.smart_cache);
    moecpu.value = String(model.settings.moe_cpu_layers);
    updateEstimate();
  }

  async function refresh() {
    const result = await api("/api/model");
    if (result.ok) render(result.body);
  }

  async function save(event) {
    event.preventDefault();
    saveNote.textContent = "Speichere …";
    const result = await api("/api/model/settings", {
      method: "PUT",
      body: { context_size: Number(context.value), kv_cache: kv.value, smart_cache: Number(smart.value), moe_cpu_layers: Number(moecpu.value) },
    });
    if (!result.ok) {
      saveNote.textContent = ((result.body && result.body.detail) || {}).message || "Nicht gespeichert.";
      return;
    }
    saveNote.textContent = result.body.restart_required ? "Gespeichert. Wirkt nach einem Neustart von KoboldCpp." : "Gespeichert.";
    refresh();
  }

  async function restart() {
    if (!window.confirm("KoboldCpp neu starten? Für ein bis drei Minuten antwortet Anton nur mit Sofortauskünften.")) return;
    const result = await api("/api/model/restart", { method: "POST" });
    measureNote.textContent = result.ok ? "Startet neu …" : ((result.body && result.body.detail) || {}).message || "Geht gerade nicht.";
    refresh();
  }

  async function measure() {
    measureButton.disabled = true;
    measureNote.textContent = "Misst …";
    const result = await api("/api/model/measure", { method: "POST" });
    if (result.ok) {
      const m = result.body;
      const first = m.first_token_ms != null ? `erstes Wort nach ${(m.first_token_ms / 1000).toFixed(1).replace(".", ",")} s, ` : "";
      measureNote.textContent = `${first}${m.tokens_per_s ? `${String(m.tokens_per_s).replace(".", ",")} Tokens/s` : "Tokens/s unbekannt"}, insgesamt ${(m.total_ms / 1000).toFixed(1).replace(".", ",")} s.`;
    } else {
      measureNote.textContent = ((result.body && result.body.detail) || {}).message || "Geht gerade nicht.";
    }
    refresh();
  }

  form.addEventListener("submit", save);
  context.addEventListener("change", updateEstimate);
  kv.addEventListener("change", updateEstimate);

  return {
    el,
    show() {
      refresh();
      clearInterval(timer);
      timer = setInterval(refresh, REFRESH_MS);
    },
    hide() {
      clearInterval(timer);
    },
  };
}
