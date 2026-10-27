# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The pure parts of the WebUI JavaScript, run with node when it is installed (P2-02)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN = ROOT / "frontend/app/js/markdown.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")


def parse(text: str) -> list[dict]:
    script = (
        f"import {{ parse }} from {json.dumps(MARKDOWN.as_uri())};"
        "let s='';process.stdin.on('data',d=>s+=d);"
        "process.stdin.on('end',()=>console.log(JSON.stringify(parse(s))));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=text,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def test_paragraph_with_bold_italic_code_and_line_break():
    (block,) = parse("Hallo **Moritz**, *kursiv* und `x = 1`.\nZweite Zeile")
    kinds = [node["t"] for node in block["inline"]]
    assert block["type"] == "paragraph"
    assert kinds == ["text", "strong", "text", "em", "text", "code", "text", "br", "text"]


def test_headings_lists_quotes_and_code_blocks():
    blocks = parse(
        "## Titel\n- eins\n- zwei\n\n3. drei\n4. vier\n\n> Zitat\n\n```py\nprint(1)\n```"
    )
    assert [b["type"] for b in blocks] == ["heading", "ul", "ol", "quote", "code"]
    assert blocks[2]["start"] == 3 and blocks[4] == {
        "type": "code",
        "lang": "py",
        "text": "print(1)",
    }


def test_a_streaming_answer_with_an_open_code_block_or_bold_stays_readable():
    assert parse("```js\nnoch offen")[0]["text"] == "noch offen"
    (block,) = parse("Das ist **noch offen")
    assert block["inline"] == [{"t": "text", "v": "Das ist **noch offen"}]


def test_links_and_bare_addresses_but_never_markup():
    (block,) = parse("[Quelle](https://tagesschau.de) und https://example.org/a. <b>fett</b>")
    links = [n for n in block["inline"] if n["t"] == "link"]
    assert [link["href"] for link in links] == ["https://tagesschau.de", "https://example.org/a"]
    assert block["inline"][-1] == {"t": "text", "v": ". <b>fett</b>"}  # stays text, never HTML


def test_snake_case_is_not_italic():
    (block,) = parse("snake_case_name")
    assert block["inline"] == [{"t": "text", "v": "snake_case_name"}]


def test_render_refuses_javascript_links():
    """render() only builds http(s) links (checked in the source: there is no DOM under node)."""
    source = MARKDOWN.read_text(encoding="utf-8")
    assert 'url.protocol === "https:" || url.protocol === "http:"' in source
    assert "innerHTML" not in source
