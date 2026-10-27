// SPDX-License-Identifier: LicenseRef-MSOL-1.1
// Markdown of Anton's answers → DOM, never as HTML strings (ADR-040). parse() is pure (tested with node),
// render() builds elements. Unfinished input (a streaming answer) is fine: an open code block runs to
// the end, an unclosed ** stays text.

// -- parse: text → blocks ----------------------------------------------------------------------------
const FENCE = /^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,4})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const NUMBER = /^\s{0,3}(\d{1,3})[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;

export function parse(source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = line.match(FENCE);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !(lines[i].match(FENCE) && lines[i].trim().startsWith(fence[1]))) body.push(lines[i++]);
      i += 1;
      blocks.push({ type: "code", lang: fence[2] || "", text: body.join("\n") });
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, inline: inline(heading[2]) });
      i += 1;
      continue;
    }
    if (RULE.test(line)) { blocks.push({ type: "rule" }); i += 1; continue; }
    if (QUOTE.test(line)) {
      const body = [];
      while (i < lines.length && QUOTE.test(lines[i])) body.push(lines[i++].match(QUOTE)[1]);
      blocks.push({ type: "quote", blocks: parse(body.join("\n")) });
      continue;
    }
    const listKind = BULLET.test(line) ? "ul" : NUMBER.test(line) ? "ol" : null;
    if (listKind) {
      const pattern = listKind === "ul" ? BULLET : NUMBER;
      const items = [];
      const start = listKind === "ol" ? Number(line.match(NUMBER)[1]) : 1;
      while (i < lines.length && lines[i].trim()) {
        const m = lines[i].match(pattern);
        if (m) items.push(m[m.length - 1]);
        else if (/^\s+\S/.test(lines[i]) && items.length) items[items.length - 1] += " " + lines[i].trim();
        else break;
        i += 1;
      }
      blocks.push({ type: listKind, start, items: items.map(inline) });
      continue;
    }
    const para = [];
    while (
      i < lines.length && lines[i].trim() &&
      !FENCE.test(lines[i]) && !HEADING.test(lines[i]) && !QUOTE.test(lines[i]) &&
      !BULLET.test(lines[i]) && !NUMBER.test(lines[i]) && !RULE.test(lines[i])
    ) para.push(lines[i++]);
    blocks.push({ type: "paragraph", inline: inline(para.join("\n")) });
  }
  return blocks;
}

const TOKEN = /(`+)([^`]|[^`][\s\S]*?[^`])\1|\*\*([^*\n](?:[\s\S]*?[^*\n])?)\*\*|__([^_\n](?:[\s\S]*?[^_\n])?)__|\*([^*\s](?:[^*\n]*[^*\s])?)\*|(?<![\w])_([^_\s](?:[^_\n]*[^_\s])?)_(?![\w])|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])|\n/g;

export function inline(text) {
  const out = [];
  let last = 0;
  const push = (node) => {
    const prev = out[out.length - 1];
    if (node.t === "text" && prev && prev.t === "text") prev.v += node.v;
    else out.push(node);
  };
  for (const m of String(text).matchAll(TOKEN)) {
    if (m.index > last) push({ t: "text", v: text.slice(last, m.index) });
    last = m.index + m[0].length;
    if (m[2] !== undefined) push({ t: "code", v: m[2].trim() || m[2] });
    else if (m[3] !== undefined || m[4] !== undefined) push({ t: "strong", c: inline(m[3] ?? m[4]) });
    else if (m[5] !== undefined || m[6] !== undefined) push({ t: "em", c: inline(m[5] ?? m[6]) });
    else if (m[7] !== undefined) push({ t: "link", href: m[8], c: inline(m[7]) });
    else if (m[9] !== undefined) push({ t: "link", href: m[9], c: [{ t: "text", v: m[9] }] });
    else push({ t: "br" });
  }
  if (last < text.length) push({ t: "text", v: text.slice(last) });
  return out;
}

// -- render: blocks → DOM ------------------------------------------------------------------------------
function safeHref(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch (_) {
    return null;
  }
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function renderInline(nodes, parent) {
  for (const node of nodes) {
    if (node.t === "text") parent.append(document.createTextNode(node.v));
    else if (node.t === "br") parent.append(el("br"));
    else if (node.t === "code") { const c = el("code"); c.textContent = node.v; parent.append(c); }
    else if (node.t === "strong" || node.t === "em") { const s = el(node.t); renderInline(node.c, s); parent.append(s); }
    else if (node.t === "link") {
      const href = safeHref(node.href);
      if (!href) { renderInline(node.c, parent); continue; }
      const a = el("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      renderInline(node.c, a);
      parent.append(a);
    }
  }
  return parent;
}

function codeBlock(block) {
  const wrap = el("div", "codeblock");
  const bar = el("div", "codebar");
  const lang = el("span");
  lang.textContent = block.lang || "Code";
  const copy = el("button", "ghost small-button");
  copy.type = "button";
  copy.textContent = "Kopieren";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(block.text);
      copy.textContent = "Kopiert";
    } catch (_) {
      copy.textContent = "Geht nicht";
    }
    setTimeout(() => { copy.textContent = "Kopieren"; }, 1500);
  });
  bar.append(lang, copy);
  const pre = el("pre");
  const code = el("code");
  code.textContent = block.text;
  pre.append(code);
  wrap.append(bar, pre);
  return wrap;
}

export function render(blocks, parent = document.createDocumentFragment()) {
  for (const block of blocks) {
    if (block.type === "paragraph") parent.append(renderInline(block.inline, el("p")));
    else if (block.type === "heading") parent.append(renderInline(block.inline, el(`h${Math.min(block.level + 2, 6)}`)));
    else if (block.type === "code") parent.append(codeBlock(block));
    else if (block.type === "rule") parent.append(el("hr"));
    else if (block.type === "quote") parent.append(render(block.blocks, el("blockquote")));
    else if (block.type === "ul" || block.type === "ol") {
      const list = el(block.type);
      if (block.type === "ol" && block.start !== 1) list.start = block.start;
      for (const item of block.items) list.append(renderInline(item, el("li")));
      parent.append(list);
    }
  }
  return parent;
}

export function markdown(text) {
  const box = el("div", "md");
  render(parse(text), box);
  return box;
}
