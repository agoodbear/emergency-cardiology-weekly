"""L1 webscraper 的純函式：關鍵字比對、RSS 解析、Google News 標題清理。不連網。"""
import asyncio

import httpx

from src import webscraper as ws


# ── 關鍵字 word-boundary ─────────────────────────────────────────────────────

def test_short_acronyms_do_not_match_inside_words():
    # README 維護表記載的歷史 bug：AF 吃到 after、OMI 吃到 medetomidine、PEA 吃到 pearl
    assert not ws._is_bc_relevant("after the medetomidine pearl session")


def test_short_acronyms_match_as_words():
    assert ws._is_bc_relevant("New-onset AF in the ED")
    assert ws._is_bc_relevant("Is this OMI?")


def test_extract_tags_dedup_and_canonical_case():
    tags = ws._extract_tags("stemi STEMI ecg then STEMI again")
    assert tags == ["STEMI", "ECG"]


def test_rfc_to_iso():
    assert ws._rfc_to_iso("Wed, 29 Apr 2026 14:48:08 +0000") == "2026-04-29"
    assert ws._rfc_to_iso("not a date") is None


# ── RSS ──────────────────────────────────────────────────────────────────────

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <item>
    <title>Hyperacute T waves: an OMI case</title>
    <link>https://drsmithsecgblog.com/hyperacute/</link>
    <pubDate>Mon, 05 Oct 2026 10:00:00 +0000</pubDate>
    <description>&lt;p&gt;A 60yo with chest pain and a subtle ECG.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Trauma bay airway pearls for after hours</title>
    <link>https://example.org/airway</link>
    <description>No cardiology here at all</description>
  </item>
  <item>
    <title>short</title>
    <link>https://example.org/short</link>
  </item>
</channel></rss>"""


def test_parse_rss_filters_and_strips_html():
    arts = ws._parse_rss_items(RSS, "Dr Smith ECG Blog", bc_filter=True)
    assert [a.url for a in arts] == ["https://drsmithsecgblog.com/hyperacute/"]
    a = arts[0]
    assert a.published == "2026-10-05"
    assert "<p>" not in a.summary and "subtle ECG" in a.summary
    assert "OMI" in a.tags and "ECG" in a.tags


def test_parse_rss_no_filter_keeps_non_ecg_but_drops_short_titles():
    arts = ws._parse_rss_items(RSS, "X", bc_filter=False)
    assert len(arts) == 2   # "short" (<10 字) 一律丟


def test_parse_rss_falls_back_to_content_encoded():
    xml = RSS.replace("<description>&lt;p&gt;A 60yo with chest pain and a subtle ECG.&lt;/p&gt;</description>",
                      "<content:encoded>&lt;p&gt;Wellens pattern&lt;/p&gt;</content:encoded>")
    arts = ws._parse_rss_items(xml, "X", bc_filter=True)
    assert arts and "Wellens" in arts[0].summary


# ── Google News ──────────────────────────────────────────────────────────────

GNEWS = """<?xml version="1.0"?><rss><channel>
<item><title>New AF ablation data presented - American College of Cardiology</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Tue, 06 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>VIKTORIA-1 ECG substudy | ACC News</title>
<link>https://news.google.com/rss/articles/def</link></item>
<item><title>Membership renewal for ECG fans - ACC</title>
<link>https://news.google.com/rss/articles/noise</link></item>
<item><title>Annual gala dinner announcement - ACC</title>
<link>https://news.google.com/rss/articles/irrelevant</link></item>
</channel></rss>"""


def _run_gnews(src):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text=GNEWS)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ws._fetch_google_news(c, src)

    return asyncio.run(go()), seen


def test_google_news_title_cleanup_noise_and_query():
    src = {"name": "ACC", "domain": "acc.org", "query": "ECG OR arrhythmia",
           "noise_filter": "membership|gala", "max_items": 10}
    arts, seen = _run_gnews(src)
    assert len(seen) == 1 and "site:acc.org+ECG+OR+arrhythmia" in seen[0]
    titles = [a.title for a in arts]
    assert titles == ["New AF ablation data presented", "VIKTORIA-1 ECG substudy"]
    assert arts[0].published == "2026-10-06"
    assert arts[0].url == "https://news.google.com/rss/articles/abc"


def test_google_news_http_error_returns_empty():
    async def go():
        t = httpx.MockTransport(lambda r: httpx.Response(503))
        async with httpx.AsyncClient(transport=t) as c:
            return await ws._fetch_google_news(c, {"name": "X", "domain": "x.org"})
    assert asyncio.run(go()) == []


def test_format_articles_md_escapes_pipe_and_handles_empty():
    arts = [ws.Article(title="A | B ECG", url="https://u", source="S", published=None, tags=["ECG"])]
    md = ws.format_articles_md({"S": arts, "Empty": []})
    assert "A ｜ B ECG" in md and "| — |" in md
    assert "_本週未取得相關文章_" in md
