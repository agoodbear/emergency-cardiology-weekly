"""Scrape latest topic-relevant articles from configured web sources."""

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from . import config

DEFAULT_GOOGLE_NEWS_QUERY = "ECG OR EKG OR arrhythmia"


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: Optional[str] = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)


# Word-boundary keyword matcher.
# Without \b, short abbreviations like "AF", "OMI", "PEA" match inside
# unrelated words (after, medetomidine, pearl). Sort by length-desc so that
# regex alternation picks the longest match first (e.g. "atrial fibrillation"
# over "AF").
@lru_cache(maxsize=1)
def _keyword_regex() -> re.Pattern:
    kws = sorted(config.keywords(), key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(re.escape(kw) for kw in kws) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


@lru_cache(maxsize=1)
def _keyword_canonical_map() -> dict[str, str]:
    return {k.lower(): k for k in config.keywords()}


def _is_bc_relevant(text: str) -> bool:
    return bool(_keyword_regex().search(text))


def _extract_tags(text: str) -> list[str]:
    canon = _keyword_canonical_map()
    seen, ordered = set(), []
    for m in _keyword_regex().findall(text):
        key = m.lower()
        if key not in seen and key in canon:
            seen.add(key)
            ordered.append(canon[key])
    return ordered


def _rfc_to_iso(rfc_date: str) -> Optional[str]:
    try:
        return parsedate_to_datetime(rfc_date).date().isoformat()
    except Exception:
        return None


def _parse_rss_items(xml_text: str, source_name: str, bc_filter: bool = True) -> list[Article]:
    soup = BeautifulSoup(xml_text, "lxml-xml")
    articles = []
    for item in soup.find_all("item"):
        title_el = item.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title or len(title) < 10:
            continue

        link_el = item.find("link")
        url = ""
        if link_el:
            url = link_el.get_text(strip=True)
            if not url:
                sib = link_el.next_sibling
                url = sib.strip() if isinstance(sib, str) else ""

        pubdate_el = item.find("pubDate")
        pub = _rfc_to_iso(pubdate_el.get_text(strip=True)) if pubdate_el else None

        desc_el = item.find("description") or item.find("content:encoded")
        summary = ""
        if desc_el:
            raw = desc_el.get_text(strip=True)
            summary = BeautifulSoup(raw, "html.parser").get_text()[:300]

        combined = title + " " + summary
        if bc_filter and not _is_bc_relevant(combined):
            continue

        articles.append(Article(
            title=title,
            url=url,
            source=source_name,
            published=pub,
            summary=summary.strip(),
            tags=_extract_tags(combined),
        ))
    return articles


async def _fetch_rss(client: httpx.AsyncClient, src: dict) -> list[Article]:
    try:
        r = await client.get(src["url"], timeout=20)
        if r.status_code != 200:
            return []
        return _parse_rss_items(
            r.text,
            src["name"],
            bc_filter=src.get("bc_filter", True),
        )
    except Exception:
        return []


async def _fetch_google_news(client: httpx.AsyncClient, src: dict) -> list[Article]:
    domain = src["domain"]
    max_items = src.get("max_items", 20)
    noise_pat = re.compile(src["noise_filter"], re.I) if src.get("noise_filter") else None
    query_term = src.get("query", DEFAULT_GOOGLE_NEWS_QUERY)

    feed_url = (
        f"https://news.google.com/rss/search"
        f"?q=site:{domain}+{quote_plus(query_term)}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        r = await client.get(feed_url, timeout=20)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "lxml-xml")
    articles = []

    for item in soup.find_all("item")[:max_items]:
        title_el = item.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title or len(title) < 10:
            continue

        # Strip site-name suffixes added by Google News:
        #   "Title | Site Name"  — pipe is unambiguous separator, strip everything after
        #   "Title - Site Name"  — only strip if suffix starts with a capital (site name)
        #                          to avoid cutting "VIKTORIA-1" or "HR+/HER2–" mid-title
        title = re.sub(r"\s*\|\s*[^|]*$", "", title).strip()
        title = re.sub(r"\s*-\s*[A-Z][^-]{2,45}$", "", title).strip()

        link_el = item.find("link")
        url = ""
        if link_el:
            sib = link_el.next_sibling
            url = sib.strip() if isinstance(sib, str) else link_el.get_text(strip=True)

        pubdate_el = item.find("pubDate")
        pub = _rfc_to_iso(pubdate_el.get_text(strip=True)) if pubdate_el else None

        if noise_pat and noise_pat.search(title):
            continue
        if not _is_bc_relevant(title):
            continue

        articles.append(Article(
            title=title,
            url=url,
            source=src["name"],
            published=pub,
            summary="",
            tags=_extract_tags(title),
        ))

    return articles


_ECGWEEKLY_SITEMAP = "https://ecgweekly.com/sitemap.xml"
_ECGWEEKLY_WORKOUT_RE = re.compile(r"^https?://(?:www\.)?ecgweekly\.com/weekly-workout/([^/?#]+)/?$")
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _slug_to_title(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-") if w)


def _parse_ecgweekly_sitemap(xml_text: str, source: str, max_items: int) -> list[Article]:
    """Pull weekly-workout URLs (+ lastmod as date) out of the sitemap XML.

    URLs are normalised to no trailing slash (matches the post-2026-09-08
    Next.js site). Newest lastmod first; entries without lastmod keep
    sitemap order after the dated ones.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    entries: list[tuple[str, str, Optional[str]]] = []
    seen: set[str] = set()
    for node in root.iter(f"{_SITEMAP_NS}url"):
        loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
        m = _ECGWEEKLY_WORKOUT_RE.match(loc)
        if not m:
            continue
        url = loc.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        lastmod = (node.findtext(f"{_SITEMAP_NS}lastmod") or "").strip()[:10] or None
        entries.append((url, m.group(1), lastmod))

    dated = sorted((e for e in entries if e[2]), key=lambda e: e[2], reverse=True)
    undated = [e for e in entries if not e[2]]
    articles: list[Article] = []
    for url, slug, lastmod in (dated + undated)[:max_items]:
        title = _slug_to_title(slug)
        articles.append(Article(
            title=title,
            url=url,
            source=source,
            published=lastmod,
            summary="",
            tags=_extract_tags(title),
        ))
    return articles


async def _fetch_ecgweekly(client: httpx.AsyncClient, src: dict) -> list[Article]:
    """ECG Weekly (Amal Mattu) -- exactly ONE anonymous request per run.

    The paid account was locked for automated access (2026-10-06), so we no
    longer open the archive page or individual workout pages. Only the public
    sitemap is fetched; title comes from the slug, date from <lastmod>.
    Any failure returns [] with no retry.
    """
    url = src.get("url", _ECGWEEKLY_SITEMAP)
    max_items = src.get("max_items", 15)
    try:
        r = await client.get(url, timeout=20)
        if r.status_code != 200:
            return []
        return _parse_ecgweekly_sitemap(r.text, src["name"], max_items)
    except Exception:
        return []


async def fetch_all(days: int = 7) -> dict[str, list[Article]]:
    """Fetch articles from all configured sources. Returns {source_name: [Article]}."""
    headers = config.http_headers()
    sources = config.web_sources()

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        tasks = []
        for src in sources:
            if src["type"] == "rss":
                tasks.append(_fetch_rss(client, src))
            elif src["type"] == "google_news":
                tasks.append(_fetch_google_news(client, src))
            elif src["type"] == "ecgweekly":
                tasks.append(_fetch_ecgweekly(client, src))

        results_list = await asyncio.gather(*tasks)

    return {src["name"]: arts for src, arts in zip(sources, results_list)}


def format_articles_md(results: dict[str, list[Article]]) -> str:
    """Render scraped articles as a markdown section for the weekly report."""
    source_names = " / ".join(results.keys())
    lines = [f"\n## 媒體動態 — {source_names}\n"]
    for source, articles in results.items():
        if not articles:
            lines.append(f"\n### {source}\n\n_本週未取得相關文章_\n")
            continue
        lines.append(f"\n### {source}（{len(articles)} 篇 ECG 相關）\n")
        lines.append("| 標題 | 日期 | 關鍵詞 |")
        lines.append("|------|------|--------|")
        for a in articles[:15]:
            date_str = a.published or "—"
            tags_str = ", ".join(a.tags[:4])
            # Escape pipes in title to avoid breaking Markdown table columns
            safe_title = a.title.replace("|", "｜")
            title_md = f"[{safe_title}]({a.url})"
            lines.append(f"| {title_md} | {date_str} | {tags_str} |")
        lines.append("")
    return "\n".join(lines)
