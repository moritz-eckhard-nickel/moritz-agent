# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Files in the WebUI chat (docs/plan/15 P2-05): reading text and PDF, upload, the model sees them."""

from __future__ import annotations

import asyncio
import io

import pytest

from moritz_agent.agent.context import DOCUMENTS_INTRO
from moritz_agent.storage.files import MAX_BYTES, FileRejected, extract

from .fake_model import text_chunks
from .system_util import running_system


def pdf_with_text(*pages: str) -> bytes:
    """A small, valid PDF with one line of text per page (Helvetica, no compression)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n{content.decode('latin-1')}\nendstream"
        )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def blank_pdf(password: str = "") -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


# -- reading --------------------------------------------------------------------------------------------
def test_text_files_in_utf8_and_windows_encoding():
    assert extract("notiz.md", "Grüße aus Weilburg".encode()).text == "Grüße aus Weilburg"
    assert extract("alt.txt", "Grüße".encode("cp1252")).text == "Grüße"
    assert extract("liste.csv", b"\xef\xbb\xbfa;b\n1;2").text == "a;b\n1;2"  # BOM gone


@pytest.mark.parametrize(
    ("name", "data", "reason"),
    [
        ("bild.png", b"\x89PNG\r\n\x1a\n", "nur Text und PDF"),
        ("leer.txt", b"   \n", "leer"),
        ("programm.txt", b"\x00\x01\x02\x00" * 100, "keine Textdatei"),
    ],
)
def test_what_cannot_be_read_says_why(name, data, reason):
    with pytest.raises(FileRejected, match=reason):
        extract(name, data)


def test_pdf_text_comes_with_page_numbers():
    result = extract("giraffen.pdf", pdf_with_text("Giraffen sind hoch", "Sie fressen Blaetter"))
    assert result.kind == "pdf" and result.pages == 2
    assert "--- Seite 1 ---\nGiraffen sind hoch" in result.text and "Seite 2" in result.text


def test_scanned_password_and_broken_pdfs_say_why():
    with pytest.raises(FileRejected, match="keine lesbare Schrift"):
        extract("scan.pdf", blank_pdf())
    with pytest.raises(FileRejected, match="Passwort"):
        extract("geheim.pdf", blank_pdf("geheim"))
    with pytest.raises(FileRejected, match="kaputt"):
        extract("kaputt.pdf", b"%PDF-1.4\nquatsch")


# -- in the chat --------------------------------------------------------------------------------------------
async def upload(client, chat, name, data):
    return await client.post(f"/api/files?chat={chat}&name={name}", content=data)


def test_the_model_reads_the_file_as_data_and_keeps_it_for_follow_ups(tmp_path):
    async def body(system):
        system.model.script = [text_chunks("Es geht um Giraffen."), text_chunks("Blätter.")]
        async with system.client() as client:
            await system.login(client)
            info = (
                await upload(client, "w-1", "giraffen.pdf", pdf_with_text("Giraffen sind hoch"))
            ).json()
            first = await client.post(
                "/api/chat",
                json={
                    "message": "Was ist 17 mal 23?",
                    "conversation_id": "w-1",
                    "files": [info["id"]],
                },
            )
            second = await client.post(
                "/api/chat", json={"message": "Und was fressen die?", "conversation_id": "w-1"}
            )
            history = (await client.get("/api/conversations?chat=w-1")).json()["items"][0]
            detail = (await client.get(f"/api/conversations/{history['id']}")).json()
        return info, first.json(), second.json(), system.model.requests, detail

    info, first, second, requests, detail = scenario(tmp_path, body, model=True)
    assert info["kind"] == "pdf" and info["pages"] == 1 and "external_id" not in info
    # with a file the instant answers are skipped: even "17 mal 23" goes to the model
    assert first["text"] == "Es geht um Giraffen." and len(requests) == 2
    for request in requests:  # the file stays in the conversation for the follow-up
        system_prompt = request["messages"][0]["content"]
        assert DOCUMENTS_INTRO in system_prompt and 'name="giraffen.pdf"' in system_prompt
        assert "Giraffen sind hoch" in system_prompt
    assert second["text"] == "Blätter."
    question = detail["messages"][0]
    assert question["meta"]["files"] == [{"id": info["id"], "name": "giraffen.pdf"}]


def test_a_file_of_another_chat_is_ignored(tmp_path):
    async def body(system):
        system.model.script = [text_chunks("Ok.")]
        async with system.client() as client:
            await system.login(client)
            info = (await upload(client, "w-a", "geheim.txt", "Nur für Chat A".encode())).json()
            await client.post(
                "/api/chat",
                json={
                    "message": "Was steht drin?",
                    "conversation_id": "w-b",
                    "files": [info["id"]],
                },
            )
        return system.model.requests

    requests = scenario(tmp_path, body, model=True)
    assert "Nur für Chat A" not in requests[0]["messages"][0]["content"]


def test_download_is_always_an_attachment_and_delete_works(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            info = (await upload(client, "w-1", "seite.html", b"<script>alert(1)</script>")).json()
            down = await client.get(f"/api/files/{info['id']}")
            deleted = (await client.delete(f"/api/files/{info['id']}")).status_code
            gone = (await client.get(f"/api/files/{info['id']}")).status_code
            bad = (await client.get("/api/files/../../passwords.txt")).status_code
        return down, deleted, gone, bad

    down, deleted, gone, bad = scenario(tmp_path, body)
    assert down.headers["content-type"] == "application/octet-stream"
    assert down.headers["content-disposition"].startswith("attachment;")
    assert down.content == b"<script>alert(1)</script>"
    assert deleted == 200 and gone == 404 and bad == 404


def test_too_big_unreadable_and_without_login(tmp_path):
    async def body(system):
        async with system.client() as client:
            anonymous = (await upload(client, "w-1", "a.txt", b"hallo")).status_code
            await system.login(client)
            big = await upload(client, "w-1", "gross.txt", b"x" * (MAX_BYTES + 1))
            image = await upload(client, "w-1", "bild.png", b"\x89PNG\r\n\x1a\n")
        return anonymous, big, image

    anonymous, big, image = scenario(tmp_path, body)
    assert anonymous == 401 and big.status_code == 413
    assert image.status_code == 422 and "nur Text und PDF" in image.json()["detail"]["message"]


def test_files_go_with_their_conversation(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            info = (await upload(client, "w-9", "a.txt", b"Notiz")).json()
            await client.post(
                "/api/chat",
                json={
                    "message": "Was ist 2 mal 2?",
                    "conversation_id": "w-9",
                    "files": [info["id"]],
                },
            )
            item = (await client.get("/api/conversations?chat=w-9")).json()["items"][0]
            await client.delete(f"/api/conversations/{item['id']}")
            return (await client.get(f"/api/files/{info['id']}")).status_code

    assert scenario(tmp_path, body) == 404
