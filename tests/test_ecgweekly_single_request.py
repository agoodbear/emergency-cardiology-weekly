"""ECG Weekly 抓取只能發 1 個請求；全程用 MockTransport，不連網。"""

import asyncio

import httpx

from src import webscraper

SRC = {"name": "ECG Weekly (Amal Mattu)", "type": "ecgweekly",
       "url": "https://ecgweekly.com/sitemap.xml", "max_items": 2}

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ecgweekly.com/weekly-workout/old-wellens-pattern</loc><lastmod>2026-01-05T00:00:00.000Z</lastmod></url>
  <url><loc>https://ecgweekly.com/weekly-workout/new-stemi-mimic/</loc><lastmod>2026-09-07T10:00:00.000Z</lastmod></url>
  <url><loc>https://ecgweekly.com/weekly-workout/mid-brugada-sign</loc><lastmod>2026-05-01</lastmod></url>
  <url><loc>https://ecgweekly.com/ecgstat/some-stat</loc><lastmod>2026-09-09</lastmod></url>
  <url><loc>https://ecgweekly.com/about</loc></url>
</urlset>"""


def _run(handler):
    calls: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as c:
            return await webscraper._fetch_ecgweekly(c, SRC)

    return asyncio.run(go()), calls


def test_single_request_and_parsed_fields():
    arts, calls = _run(lambda r: httpx.Response(200, text=SITEMAP))
    assert calls == ["https://ecgweekly.com/sitemap.xml"]
    assert [a.url for a in arts] == [
        "https://ecgweekly.com/weekly-workout/new-stemi-mimic",
        "https://ecgweekly.com/weekly-workout/mid-brugada-sign",
    ]
    assert arts[0].title == "New Stemi Mimic"
    assert arts[0].published == "2026-09-07"
    assert arts[0].source == SRC["name"]


def test_bad_status_returns_empty_without_retry():
    arts, calls = _run(lambda r: httpx.Response(403, text="blocked"))
    assert arts == [] and len(calls) == 1


def test_garbage_body_returns_empty():
    arts, calls = _run(lambda r: httpx.Response(200, text="<html>not xml"))
    assert arts == [] and len(calls) == 1


def test_network_error_returns_empty():
    def boom(request):
        raise httpx.ConnectError("down")
    arts, calls = _run(boom)
    assert arts == [] and len(calls) == 1
