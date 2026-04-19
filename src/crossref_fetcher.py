"""Fetch recent journal articles from CrossRef API and pre-screen for ECG relevance."""

import asyncio
import re
import yaml
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from . import config

SOURCE_DIR = Path(__file__).parent.parent / "source"
JATS_TAG = re.compile(r"<[^>]+>")

# Pre-screen: two-tier filter.
# Tier 1 — unambiguous ECG / arrhythmia terms: pass immediately.
# Tier 2 — shared cardiology terms (cardiomyopathy, heart failure, ischemia):
#           documented here but not used by _passes_prescreen, so non-ECG
#           cardiology articles (e.g. pure HF trials, valve surgery) are
#           filtered out unless their title/abstract also contains a Tier-1 term.
_BC_DIRECT = [
    # Core ECG
    "ECG", "EKG", "electrocardiogram", "electrocardiograph", "12-lead",
    "QT interval", "QTc", "QRS", "P wave", "PR interval",
    # Arrhythmia
    "arrhythmia", "atrial fibrillation", "atrial flutter", "AFib",
    "ventricular tachycardia", "ventricular fibrillation", "SVT", "VT", "VF",
    "torsades", "premature ventricular", "PVC", "electrical storm",
    # Conduction
    "AV block", "heart block", "Mobitz", "Wenckebach", "bifascicular",
    "LBBB", "RBBB", "bundle branch block", "fascicular",
    # Channelopathy
    "Brugada", "Wolff-Parkinson-White", "WPW", "long QT", "LQTS",
    "ARVC", "CPVT", "early repolarization",
    # ACS / OMI
    "STEMI", "NSTEMI", "OMI", "occlusion myocardial", "Sgarbossa",
    "Wellens", "De Winter", "hyperacute T",
    # Devices
    "pacemaker", "implantable cardioverter", "ICD", "biventricular pacing",
    "leadless pacemaker", "loop recorder", "Holter",
    # AI / wearable
    "AI-ECG", "deep learning ECG", "Apple Watch ECG", "Kardia", "AliveCor",
    "PMcardio",
    # Resuscitation rhythms
    "cardiac arrest", "defibrillation", "cardioversion",
    "pulseless electrical activity", "asystole", "ROSC",
    # Emergency pearls
    "BRASH", "syncope", "palpitations",
]
_SHARED_TERMS = [
    "cardiomyopathy", "heart failure", "HFrEF", "HFpEF",
    "myocardial", "ischemia", "ischaemic",
    "ventricle", "ventricular", "atrial",
    "ablation", "electrophysiology",
]


@dataclass
class JournalArticle:
    title: str
    doi: str
    journal: str
    authors: list[str]
    published: Optional[str]
    abstract: str
    abstract_digest: str
    tags: list[str] = field(default_factory=list)
    url: str = ""


def _load_journals() -> list[dict]:
    data = yaml.safe_load((SOURCE_DIR / "journals.yml").read_text())
    return data.get("journals", [])


def _crossref_email() -> str:
    data = yaml.safe_load((SOURCE_DIR / "journals.yml").read_text())
    return data.get("crossref_email", "")


def _clean_abstract(raw: str) -> str:
    return re.sub(r"\s+", " ", JATS_TAG.sub("", raw)).strip()


def _digest_abstract(abstract: str, max_chars: int = 400) -> str:
    if not abstract:
        return ""
    signal_words = [
        "significantly", "improved", "reduced", "increased", "demonstrated",
        "showed", "resulted", "HR ", "hazard ratio", "OS ", "PFS ", "ORR",
        "p=", "p<", "p >", "95% CI", "median", "months", "year",
        "approved", "primary endpoint", "statistically",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", abstract)
    scored = sorted(
        ((sum(1 for w in signal_words if w.lower() in s.lower()), s) for s in sentences),
        key=lambda x: -x[0],
    )
    parts, total = [], 0
    for _, s in scored:
        if total + len(s) > max_chars:
            break
        parts.append(s)
        total += len(s)
    return " ".join(parts).strip() if parts else abstract[:max_chars]


@lru_cache(maxsize=1)
def _keyword_regex() -> re.Pattern:
    kws = sorted(config.keywords(), key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(re.escape(kw) for kw in kws) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


@lru_cache(maxsize=1)
def _keyword_canonical_map() -> dict[str, str]:
    return {k.lower(): k for k in config.keywords()}


@lru_cache(maxsize=1)
def _direct_regex() -> re.Pattern:
    terms = sorted(_BC_DIRECT, key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def _extract_tags(text: str) -> list[str]:
    canon = _keyword_canonical_map()
    seen, ordered = set(), []
    for m in _keyword_regex().findall(text):
        key = m.lower()
        if key not in seen and key in canon:
            seen.add(key)
            ordered.append(canon[key])
    return ordered


def _passes_prescreen(text: str) -> bool:
    # Word-boundary match: "AF" won't match "after", "OMI" won't match "medetomidine".
    return bool(_direct_regex().search(text))


def _pub_date(item: dict) -> Optional[str]:
    parts = (
        item.get("published", {}).get("date-parts")
        or item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or [[]]
    )
    dp = (parts or [[]])[0]
    if len(dp) >= 3:
        return f"{dp[0]:04d}-{dp[1]:02d}-{dp[2]:02d}"
    if len(dp) == 2:
        return f"{dp[0]:04d}-{dp[1]:02d}"
    if len(dp) == 1:
        return f"{dp[0]:04d}"
    return None


# ── CrossRef fetch ─────────────────────────────────────────────────────────────

async def _fetch_journal(
    client: httpx.AsyncClient,
    journal: dict,
    email: str,
) -> list[JournalArticle]:
    issn = journal["issn"]
    days_back = journal.get("days_back", 14)
    max_items = journal.get("max_items", 30)
    bc_filter = journal.get("bc_filter", True)
    from_date = (date.today() - timedelta(days=days_back)).isoformat()

    params = {
        "filter": f"issn:{issn},from-pub-date:{from_date}",
        "rows": max_items,
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,author,abstract,published,published-print,published-online,URL,container-title",
    }
    try:
        r = await client.get(
            "https://api.crossref.org/works",
            params=params,
            headers={"User-Agent": f"ecg-weekly/1.0 (mailto:{email})"},
            timeout=25,
        )
        r.raise_for_status()
    except Exception:
        return []

    articles = []
    for item in r.json().get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        if not title or len(title) < 10:
            continue
        abstract = _clean_abstract(item.get("abstract", ""))

        if bc_filter and not _passes_prescreen(title + " " + abstract):
            continue

        authors_raw = item.get("author", [])
        authors = [
            f"{a.get('family', '')} {a.get('given', '')[:1]}".strip()
            for a in authors_raw[:4]
        ]
        if len(authors_raw) > 4:
            authors.append("et al.")

        doi = item.get("DOI", "")
        journal_name = (item.get("container-title") or [journal.get("full_name", issn)])[0]

        articles.append(JournalArticle(
            title=title,
            doi=doi,
            journal=journal_name,
            authors=authors,
            published=_pub_date(item),
            abstract=abstract,
            abstract_digest=_digest_abstract(abstract),
            tags=_extract_tags(title + " " + abstract),
            url=f"https://doi.org/{doi}" if doi else item.get("URL", ""),
        ))

    return articles


async def fetch_all() -> dict[str, list[JournalArticle]]:
    journals = _load_journals()
    email = _crossref_email()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch_journal(client, j, email) for j in journals])
    return {j["name"]: arts for j, arts in zip(journals, results)}


def format_articles_md(results: dict[str, list[JournalArticle]]) -> str:
    if not any(results.values()):
        return ""

    lines = ["\n## 文獻速報 — CrossRef 期刊\n"]
    lines.append("> 資料來源：CrossRef API · 關鍵詞預篩後由 Claude 在報告生成時確認相關性\n")

    for journal_name, articles in results.items():
        if not articles:
            lines.append(f"\n### {journal_name}\n\n_本期未取得相關論文_\n")
            continue

        with_abstract = [a for a in articles if a.abstract_digest]
        without = [a for a in articles if not a.abstract_digest]

        lines.append(f"\n### {journal_name}（{len(articles)} 篇候選）\n")

        for a in with_abstract[:10]:
            lines.append(f"#### [{a.title}]({a.url})")
            lines.append(f"_{', '.join(a.authors)}_ · {a.published or '—'} · {a.journal}")
            lines.append("")
            lines.append(f"> {a.abstract_digest}")
            if a.tags:
                lines.append(f"\n`{'` `'.join(a.tags[:5])}`")
            lines.append("")

        if without:
            lines.append("**摘要未提供：**\n")
            for a in without[:8]:
                lines.append(f"- [{a.title}]({a.url}) — _{', '.join(a.authors)}_ ({a.published or '—'})")
            lines.append("")

    return "\n".join(lines)
