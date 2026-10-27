// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Small DOM helpers. Text always goes in as textContent – never as HTML (P2-01, CSP).

const SVG = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// Outline icons, 24×24, drawn with paths only.
const ICONS = {
  chat: ["M4 5h16v11H8l-4 4z"],
  status: ["M3 12h4l3-7 4 14 3-7h4"],
  plus: ["M12 5v14", "M5 12h14"],
  send: ["M4 12l16-8-6 16-3-7z"],
  stop: ["M7 7h10v10H7z"],
  history: ["M3 12a9 9 0 1 0 3-6.7", "M3 4v4h4", "M12 7v5l3 2"],
  pin: ["M6 4h12v17l-6-4-6 4z"],
  globe: ["M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18z", "M3 12h18", "M12 3c3 3 3 15 0 18", "M12 3c-3 3-3 15 0 18"],
  phone: ["M5 4h4l2 5-3 2a11 11 0 0 0 5 5l2-3 5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"],
  voice: ["M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M5 11a7 7 0 0 0 14 0", "M12 18v3"],
  edit: ["M4 20h4L19 9l-4-4L4 16z", "M13 7l4 4"],
  download: ["M12 4v11", "M7 10l5 5 5-5", "M5 20h14"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
};

export function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ICONS[name] || []) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch (_) {
    return null;
  }
}

export const store = {
  get(key) {
    try { return window.localStorage.getItem(key); } catch (_) { return null; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, value); } catch (_) { /* private mode */ }
  },
};
