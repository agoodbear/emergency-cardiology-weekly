"""Fetch recent PubMed articles by指定作者 via NCBI E-utilities.

Pattern mirrors crossref_fetcher.py — same dataclass shape so reports can merge them.
NCBI E-utilities is free, no API key needed for ≤3 req/sec.
"""

import asyncio
import re
import xml.etree.ElementTree as ET
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .crossref_fetcher import (
    _digest_abstract,
    _extract_tags,
    _passes_prescreen,
)

SOURCE_DIR = Path(__file__).parent.parent / "source"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass
class AuthorArticle:
    title: str
    pmid: str
    journal: str
    authors: list[str]
    published: Optional[str]
    abstract: str
    abstract_digest: str
    tags: list[str] = field(default_factory=list)
    url: str = ""
    matched_author: str = ""        # 哪位被監控的作者觸發這篇
    author_tag: str = ""             # 該作者的主題 tag


def _load_authors() -> tuple[list[dict], str]:
    data = yaml.safe_load((SOURCE_DIR / "authors.yml").read_text())
    return data.get("authors", []), data.get("pubmed_email", "")


def _parse_abstract(article_elem) -> str:
    parts = []
    for ab in article_elem.iter("AbstractText"):
        label = ab.get("Label")
        text = "".join(ab.itertext()).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts).strip()


def _parse_pubdate(article_elem) -> Optional[str]:
    for path in ("PubDate", "ArticleDate"):
        d = article_elem.find(f".//{path}")
        if d is None:
            continue
        y = d.findtext("Year")
        m = d.findtext("Month") or "01"
        day = d.findtext("Day") or "01"
        if not y:
            continue
        # Month can be "Jan" or "01"
        month_map = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
            "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        m = month_map.get(m, m if m.isdigit() else "01")
        try:
            return f"{int(y):04d}-{int(m):02d}-{int(day):02d}"
        except ValueError:
            return f"{y}"
    return None


def _parse_authors(article_elem) -> list[str]:
    out = []
    for a in article_elem.iter("Author"):
        last = a.findtext("LastName") or ""
        init = a.findtext("Initials") or ""
        if last:
            out.append(f"{last} {init}".strip())
        if len(out) >= 4:
            out.append("et al.")
            break
    return out


async def _esearch(client: httpx.AsyncClient, query: str, days_back: int,
                   max_items: int, email: str) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_items,
        "retmode": "json",
        "datetype": "pdat",
        "reldate": days_back,
        "tool": "ecg-weekly",
        "email": email,
    }
    try:
        r = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=20)
        r.raise_for_status()
    except Exception:
        return []
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    return ids


async def _efetch(client: httpx.AsyncClient, pmids: list[str], email: str) -> str:
    if not pmids:
        return ""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": "ecg-weekly",
        "email": email,
    }
    try:
        r = await client.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=30)
        r.raise_for_status()
    except Exception:
        return ""
    return r.text


def _parse_efetch_xml(xml_text: str, matched: str, tag: str) -> list[AuthorArticle]:
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out = []
    for art in root.iter("PubmedArticle"):
        title = (art.findtext(".//ArticleTitle") or "").strip()
        if not title:
            continue
        pmid = (art.findtext(".//PMID") or "").strip()
        journal = (art.findtext(".//Journal/Title") or art.findtext(".//ISOAbbreviation") or "").strip()
        abstract = _parse_abstract(art)
        abstract = re.sub(r"\s+", " ", abstract).strip()
        published = _parse_pubdate(art)
        authors = _parse_authors(art)

        text_for_filter = title + " " + abstract
        if not _passes_prescreen(text_for_filter):
            # 該作者本人 + ECG 關鍵字交集才入選；非 ECG 主題的作者文章丟棄
            continue

        out.append(AuthorArticle(
            title=title,
            pmid=pmid,
            journal=journal,
            authors=authors,
            published=published,
            abstract=abstract,
            abstract_digest=_digest_abstract(abstract),
            tags=_extract_tags(text_for_filter),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            matched_author=matched,
            author_tag=tag,
        ))
    return out


async def _fetch_one_author(client: httpx.AsyncClient, author: dict,
                             email: str) -> list[AuthorArticle]:
    name = author["name"]
    query = author["query"]
    days_back = author.get("days_back", 14)
    max_items = author.get("max_items", 20)
    tag = author.get("tag", "")

    pmids = await _esearch(client, query, days_back, max_items, email)
    await asyncio.sleep(0.4)        # NCBI ≤3 req/sec polite gap
    if not pmids:
        return []
    xml_text = await _efetch(client, pmids, email)
    return _parse_efetch_xml(xml_text, name, tag)


async def fetch_all() -> dict[str, list[AuthorArticle]]:
    authors, email = _load_authors()
    results = {}
    async with httpx.AsyncClient() as client:
        # 串聯跑（不平行）— NCBI 限速 ≤3 req/sec，串聯最穩
        for author in authors:
            arts = await _fetch_one_author(client, author, email)
            results[author["name"]] = arts
            await asyncio.sleep(0.4)
    return results


def format_articles_md(results: dict[str, list[AuthorArticle]]) -> str:
    if not any(results.values()):
        return ""

    lines = ["\n## 追蹤作者本週新作 — PubMed\n"]
    lines.append("> 資料來源：NCBI PubMed E-utilities · 指定作者 + ECG 關鍵字雙重過濾\n")

    for author_name, articles in results.items():
        if not articles:
            lines.append(f"\n### {author_name}\n\n_本週 PubMed 無新 ECG 相關發表_\n")
            continue

        lines.append(f"\n### {author_name}（{len(articles)} 篇）\n")
        for a in articles[:5]:
            lines.append(f"#### [{a.title}]({a.url})")
            lines.append(f"_{', '.join(a.authors)}_ · {a.published or '—'} · {a.journal}")
            lines.append("")
            if a.abstract_digest:
                lines.append(f"> {a.abstract_digest}")
            if a.tags:
                lines.append(f"\n`{'` `'.join(a.tags[:5])}`")
            lines.append("")

    return "\n".join(lines)
