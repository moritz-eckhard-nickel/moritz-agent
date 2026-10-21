# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Web search: SearXNG client, fallback chain, Wikipedia and KoboldCpp stages (P1-08)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from moritz_agent.config.settings import Search, Settings
from moritz_agent.inference import InferenceClient
from moritz_agent.research.fallbacks import KoboldWebSearch, WikipediaSearch
from moritz_agent.research.search import (
    SearchBackend,
    SearchError,
    SearchHit,
    SearchService,
    clean_text,
    encyclopedic,
)
from moritz_agent.research.searxng_client import SearxngClient
from moritz_agent.research.searxng_process import build_argv, build_env, installed

ROOT = Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


SEARXNG_ANSWER = {
    "query": "bundestag",
    "results": [
        {
            "url": "https://www.bundestag.de/",
            "title": "Deutscher <b>Bundestag</b>",
            "content": "Das Parlament &amp; seine Aufgaben.\n  Sitzungswochen.",
            "engines": ["duckduckgo", "brave"],
            "engine": "duckduckgo",
            "publishedDate": "2026-10-01T08:30:00",
        },
        {
            "url": "https://bundestag.de/presse",
            "title": "Presse",
            "content": "Zweiter Treffer derselben Domain",
            "engines": ["bing"],
        },
        {"title": "Ohne Adresse", "content": "x"},
        {"url": "javascript:alert(1)", "title": "Böse", "content": "x"},
        "kein Objekt",
        {
            "url": "https://de.wikipedia.org/wiki/Deutscher_Bundestag",
            "title": "Deutscher Bundestag – Wikipedia",
            "content": "Der Bundestag ist das Parlament.",
            "engine": "wikipedia",
        },
    ],
    "unresponsive_engines": [["google", "CAPTCHA"]],
}

WIKIPEDIA_ANSWER = {
    "batchcomplete": True,
    "query": {
        "pages": [
            {
                "pageid": 2,
                "title": "Weilburg",
                "index": 2,
                "extract": "Weilburg ist eine Stadt im Landkreis Limburg-Weilburg in Hessen.",
                "fullurl": "https://de.wikipedia.org/wiki/Weilburg",
            },
            {
                "pageid": 1,
                "title": "Weilburg (Lahn)",
                "index": 1,
                "extract": "Die Kreisstadt liegt an der Lahn.",
                "fullurl": "https://de.wikipedia.org/wiki/Weilburg_(Lahn)",
            },
            {"pageid": 3, "title": "Leer", "index": 3, "extract": ""},
        ]
    },
}


def mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def json_route(payload, status=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(status, json=payload)

    return mock(handler)


# -- text helpers -----------------------------------------------------------------------------------
def test_clean_text_removes_tags_entities_and_shortens():
    assert clean_text("Das <b>Parlament</b> &amp; mehr\n\n  hier") == "Das Parlament & mehr hier"
    long = clean_text("wort " * 200, 50)
    assert len(long) <= 55 and long.endswith("…")
    assert clean_text(None) == ""


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Wer war Konrad Adenauer", True),
        ("Was ist ein Quasar", True),
        ("aktuelle Nachrichten aus Berlin", False),
        ("Dollarkurs heute", False),
        ("Spielstand Eintracht Frankfurt", False),
    ],
)
def test_encyclopedic_questions(query, expected):
    assert encyclopedic(query) is expected


# -- SearXNG client -----------------------------------------------------------------------------
def test_searxng_client_sends_language_safesearch_and_json_format():
    calls: list[httpx.Request] = []

    async def scenario():
        client = SearxngClient(
            "http://127.0.0.1:8888",
            language="de-DE",
            safesearch=0,
            transport=json_route(SEARXNG_ANSWER, calls=calls),
        )
        try:
            return await client.search("bundestag", 5)
        finally:
            await client.aclose()

    hits = run(scenario())
    query = dict(calls[0].url.params)
    assert calls[0].url.path == "/search"
    assert query == {"q": "bundestag", "format": "json", "language": "de-DE", "safesearch": "0"}
    first = hits[0]
    assert first.title == "Deutscher Bundestag"
    assert first.snippet == "Das Parlament & seine Aufgaben. Sitzungswochen."
    assert first.domain == "bundestag.de"
    assert first.engines == ("duckduckgo", "brave")
    assert first.published == "2026-10-01"
    assert first.backend == "searxng"


def test_searxng_client_skips_entries_without_a_usable_address():
    async def scenario():
        client = SearxngClient("http://127.0.0.1:1", transport=json_route(SEARXNG_ANSWER))
        return await client.search("x", 10)

    urls = [hit.url for hit in run(scenario())]
    assert urls == [
        "https://www.bundestag.de/",
        "https://bundestag.de/presse",
        "https://de.wikipedia.org/wiki/Deutscher_Bundestag",
    ]


def test_engine_name_falls_back_to_the_single_engine_field():
    async def scenario():
        client = SearxngClient("http://127.0.0.1:1", transport=json_route(SEARXNG_ANSWER))
        return await client.search("x", 10)

    assert run(scenario())[-1].engines == ("wikipedia",)


@pytest.mark.parametrize(
    ("payload", "status", "kind"),
    [
        ({"results": []}, 500, "offline"),
        ({"no": "results"}, 200, "bad_data"),
        (["list"], 200, "bad_data"),
    ],
)
def test_searxng_client_errors(payload, status, kind):
    async def scenario():
        client = SearxngClient("http://127.0.0.1:1", transport=json_route(payload, status))
        await client.search("x", 5)

    with pytest.raises(SearchError) as err:
        run(scenario())
    assert err.value.kind == kind


def test_searxng_client_reports_unreachable_and_invalid_json():
    def refuse(request):
        raise httpx.ConnectError("down")

    def garbage(request):
        return httpx.Response(200, content=b"<html>")

    def slow(request):
        raise httpx.ReadTimeout("slow")

    for handler, kind in ((refuse, "offline"), (garbage, "bad_data"), (slow, "timeout")):

        async def scenario(handler=handler):
            client = SearxngClient("http://127.0.0.1:1", transport=mock(handler))
            await client.search("x", 5)

        with pytest.raises(SearchError) as err:
            run(scenario())
        assert err.value.kind == kind


def test_searxng_health():
    async def scenario(status):
        client = SearxngClient(
            "http://127.0.0.1:1", transport=mock(lambda r: httpx.Response(status, text="OK"))
        )
        return await client.health()

    assert run(scenario(200)) is True
    assert run(scenario(503)) is False


# -- Wikipedia ------------------------------------------------------------------------------------
def test_wikipedia_returns_intro_extracts_in_ranking_order():
    calls: list[httpx.Request] = []

    async def scenario():
        wiki = WikipediaSearch(transport=json_route(WIKIPEDIA_ANSWER, calls=calls))
        try:
            return await wiki.search("Weilburg", 5)
        finally:
            await wiki.aclose()

    hits = run(scenario())
    assert calls[0].url.host == "de.wikipedia.org"
    assert calls[0].url.params["gsrsearch"] == "Weilburg"
    assert [hit.title for hit in hits] == ["Weilburg (Lahn) – Wikipedia", "Weilburg – Wikipedia"]
    assert hits[0].backend == "wikipedia" and hits[0].domain == "de.wikipedia.org"
    assert hits[1].snippet.startswith("Weilburg ist eine Stadt")


def test_wikipedia_without_a_hit_has_no_query_key():
    async def scenario():
        wiki = WikipediaSearch(transport=json_route({"batchcomplete": True}))
        return await wiki.search("qwertzuiop", 3)

    assert run(scenario()) == []


# -- KoboldCpp stage ------------------------------------------------------------------------------------
def test_koboldcpp_stage_maps_the_websearch_answer():
    rows = [
        {
            "title": "Tagesschau",
            "url": "https://www.tagesschau.de/",
            "desc": "Nachrichten",
            "content": "Text",
        },
        {"title": "", "url": "https://x.example/", "desc": "ohne Titel"},
    ]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=rows)

    async def scenario():
        client = InferenceClient("http://127.0.0.1:1", transport=mock(handler))
        return await KoboldWebSearch(client).search("tagesschau", 5)

    hits = run(scenario())
    assert seen == [("/api/extra/websearch", {"q": "tagesschau"})]
    assert len(hits) == 1
    assert hits[0].domain == "tagesschau.de" and hits[0].engines == ("duckduckgo",)
    assert hits[0].content == "Text"


def test_koboldcpp_stage_turns_inference_errors_into_search_errors():
    def refuse(request):
        raise httpx.ConnectError("down")

    async def scenario():
        client = InferenceClient("http://127.0.0.1:1", transport=mock(refuse))
        await KoboldWebSearch(client).search("x", 5)

    with pytest.raises(SearchError) as err:
        run(scenario())
    assert err.value.kind == "offline"


# -- fallback chain ---------------------------------------------------------------------------------
class Fake:
    def __init__(self, name, hits=None, error=None, delay=0.0):
        self.name = name
        self.hits = hits or []
        self.error = error
        self.delay = delay
        self.queries: list[str] = []

    async def search(self, query: str, limit: int):
        self.queries.append(query)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return list(self.hits)


def hit(domain, backend="searxng", n=0):
    return SearchHit(f"{domain} {n}", f"https://{domain}/{n}", "Text", domain, backend)


def service(*backends: SearchBackend, **cfg) -> SearchService:
    return SearchService(Search(**cfg), {b.name: b for b in backends})


def test_first_backend_with_hits_wins_and_later_ones_stay_untouched():
    searx = Fake("searxng", [hit("a.de"), hit("b.de")])
    kobold = Fake("koboldcpp", [hit("c.de", "koboldcpp")])
    outcome = run(service(searx, kobold).search("  Was   kostet ein Brot  "))
    assert outcome.ok and outcome.backend == "searxng" and outcome.tried == ["searxng"]
    assert searx.queries == ["Was kostet ein Brot"]
    assert kobold.queries == []


def test_hits_are_deduplicated_by_domain_and_limited():
    searx = Fake(
        "searxng", [hit("a.de", n=1), hit("a.de", n=2)] + [hit(f"s{i}.de") for i in range(9)]
    )
    outcome = run(service(searx).search("brot", 3))
    assert [h.domain for h in outcome.hits] == ["a.de", "s0.de", "s1.de"]
    assert outcome.hits[0].url == "https://a.de/1"


def test_limit_never_exceeds_the_configured_maximum():
    searx = Fake("searxng", [hit(f"s{i}.de") for i in range(10)])
    outcome = run(service(searx, max_results=4).search("brot", 99))
    assert len(outcome.hits) == 4


def test_timeout_and_empty_answers_fall_through_to_the_next_backend():
    searx = Fake("searxng", delay=1.0)
    kobold = Fake("koboldcpp", [])
    wiki = Fake("wikipedia", [hit("de.wikipedia.org", "wikipedia")])
    outcome = run(service(searx, kobold, wiki, timeout_s=0.05).search("Konrad Adenauer"))
    assert outcome.backend == "wikipedia"
    assert outcome.tried == ["searxng", "koboldcpp", "wikipedia"]
    assert outcome.errors == {"searxng": "timeout", "koboldcpp": "empty"}


def test_errors_of_a_backend_are_remembered_and_the_chain_goes_on():
    searx = Fake("searxng", error=SearchError("offline"))
    kobold = Fake("koboldcpp", [hit("x.de", "koboldcpp")])
    outcome = run(service(searx, kobold).search("brot"))
    assert outcome.backend == "koboldcpp" and outcome.errors == {"searxng": "offline"}


def test_nothing_answers_gives_an_empty_outcome_with_all_reasons():
    searx = Fake("searxng", error=SearchError("offline"))
    kobold = Fake("koboldcpp", error=SearchError("timeout"))
    outcome = run(service(searx, kobold).search("brot"))
    assert not outcome.ok and outcome.backend is None
    assert outcome.errors == {"searxng": "offline", "koboldcpp": "timeout"}


def test_wikipedia_is_skipped_for_questions_about_now():
    searx = Fake("searxng", [])
    wiki = Fake("wikipedia", [hit("de.wikipedia.org", "wikipedia")])
    outcome = run(service(searx, wiki).search("aktuelle Nachrichten"))
    assert not outcome.ok and wiki.queries == []
    assert outcome.errors["wikipedia"] == "skipped" and outcome.tried == ["searxng"]


def test_backends_follow_the_configured_order_and_unknown_names_are_ignored():
    searx = Fake("searxng", [hit("a.de")])
    kobold = Fake("koboldcpp", [hit("b.de", "koboldcpp")])
    chain = service(searx, kobold, backends=["gibtsnicht", "koboldcpp", "searxng"])
    assert run(chain.search("brot")).backend == "koboldcpp"


def test_disabled_search_and_empty_query():
    searx = Fake("searxng", [hit("a.de")])
    assert run(service(searx, enabled=False).search("brot")).errors == {"search": "disabled"}
    assert run(service(searx).search("   ")).errors == {"search": "empty_query"}
    assert searx.queries == []


def test_very_long_queries_are_cut():
    searx = Fake("searxng", [hit("a.de")])
    run(service(searx).search("wort " * 200))
    assert len(searx.queries[0]) <= 300


def test_service_closes_its_backends():
    closed = []

    class Closing(Fake):
        async def aclose(self):
            closed.append(self.name)

    run(service(Closing("searxng"), Fake("koboldcpp")).aclose())
    assert closed == ["searxng"]


# -- SearXNG process ----------------------------------------------------------------------------------
def test_process_arguments_and_environment():
    settings = Settings()
    argv = build_argv(settings, ROOT, 18080)
    assert argv[0].endswith("runtime/searxng-venv/bin/granian")
    assert argv[argv.index("--host") + 1] == "127.0.0.1"  # loopback only
    assert argv[argv.index("--port") + 1] == "18080"
    assert argv[argv.index("--interface") + 1] == "wsgi" and argv[-1] == "searx.webapp:app"
    env = build_env(settings, ROOT, 18080)
    assert env["SEARXNG_SETTINGS_PATH"] == str(ROOT / "config/searxng/settings.yml")
    assert env["PYTHONPATH"] == str(ROOT / "third_party/searxng")
    assert env["SEARXNG_BIND_ADDRESS"] == "127.0.0.1" and env["SEARXNG_PORT"] == "18080"
    assert len(env["SEARXNG_SECRET"]) == 64
    assert env["SEARXNG_SECRET"] != build_env(settings, ROOT, 18080)["SEARXNG_SECRET"]


def test_installed_detects_the_environment(tmp_path):
    settings = Settings()
    assert installed(settings, tmp_path) is False
    (tmp_path / "runtime/searxng-venv/bin").mkdir(parents=True)
    (tmp_path / "runtime/searxng-venv/bin/granian").write_text("")
    assert installed(settings, tmp_path) is True


def test_shipped_settings_enable_json_and_stay_on_loopback():
    text = (ROOT / "config/searxng/settings.yml").read_text()
    assert "- json" in text and 'bind_address: "127.0.0.1"' in text
    assert "secret_key" not in text.replace("secret_key is generated", "")


# -- with the real SearXNG (optional: -m network, needs scripts/setup-searxng.sh) ---------------
@pytest.mark.network
def test_real_searxng_answers_healthz_and_json(tmp_path):
    settings = Settings()
    if not installed(settings, ROOT):
        pytest.skip(
            "runtime/searxng-venv fehlt (scripts/setup-searxng.sh --venv runtime/searxng-venv)"
        )
    from moritz_agent.research.searxng_process import SearxngService

    async def scenario():
        service = SearxngService(settings, ROOT)
        await service.start()
        try:
            assert await service.process.wait_ready(90)
            return await service.client.search("Weilburg", 5)
        finally:
            await service.stop()

    hits = run(scenario())
    assert all(h.url.startswith("http") for h in hits)
