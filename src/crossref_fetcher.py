"""Fetch recent journal articles from CrossRef API and classify with Claude."""

import asyncio
import os
import re
import yaml
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import anthropic
import httpx

from . import config

SOURCE_DIR = Path(__file__).parent.parent / "source"
JATS_TAG = re.compile(r"<[^>]+>")

# Pre-screen: require at least one of these before sending to LLM
# (keeps API calls low — only articles that smell oncology-related get classified)
_PRESCREEN_TERMS = [
    "breast", "mammary", "HER2", "TNBC", "CDK4", "CDK6",
    "trastuzumab", "pertuzumab", "sacituzumab", "T-DXd", "Enhertu",
    "ribociclib", "palbociclib", "abemaciclib", "olaparib", "talazoparib",
    "ESR1", "imlunestrant", "elacestrant", "fulvestrant",
    "DESTINY-Breast", "ASCENT", "NATALEE", "monarchE",
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


def _extract_tags(text: str) -> list[str]:
    tl = text.lower()
    return list(dict.fromkeys(k for k in config.keywords() if k.lower() in tl))


def _passes_prescreen(text: str) -> bool:
    tl = text.lower()
    return any(t.lower() in tl for t in _PRESCREEN_TERMS)


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


# ── LLM classifier ────────────────────────────────────────────────────────────

_STRICT_TERMS = ["breast", "mammary"]


def _strict_fallback(candidates: list[tuple[str, str]], disease: str) -> list[bool]:
    """Fallback when no API key: require disease phrase in title+abstract."""
    phrase = disease.lower()
    return [phrase in (t + " " + a).lower() for t, a in candidates]


def _llm_filter(
    candidates: list[tuple[str, str]],   # [(title, abstract), ...]
    disease: str = "breast cancer",
) -> list[bool]:
    """
    Ask Claude Haiku to classify each article as breast-cancer-relevant.
    Returns a list of bools aligned with candidates.
    Batches all titles in one API call to minimise latency/cost.
    """
    if not candidates:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # No API key — strict keyword fallback (no fail-open to avoid false positives)
        return _strict_fallback(candidates, disease)

    numbered = "\n".join(
        f"{i+1}. TITLE: {t}\n   ABSTRACT: {a[:300] or '(no abstract)'}"
        for i, (t, a) in enumerate(candidates)
    )

    prompt = f"""You are a medical literature classifier. For each article below, decide if it is primarily about {disease} — meaning the main study population or primary topic is {disease} (not just a disease that shares some biomarkers like HER2 with other cancers).

Reply with ONLY a JSON array of true/false values, one per article, in order.
Example for 3 articles: [true, false, true]

Articles:
{numbered}"""

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # parse JSON array
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            import json
            result = json.loads(match.group())
            if len(result) == len(candidates):
                return [bool(r) for r in result]
    except Exception:
        pass

    return _strict_fallback(candidates, disease)  # API error — strict fallback


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
            headers={"User-Agent": f"breast-cancer-uptodate/1.0 (mailto:{email})"},
            timeout=25,
        )
        r.raise_for_status()
    except Exception:
        return []

    # Build raw candidates
    raw_items = r.json().get("message", {}).get("items", [])
    candidates = []
    raw_map = []   # keep originals aligned

    for item in raw_items:
        title = (item.get("title") or [""])[0]
        if not title or len(title) < 10:
            continue
        abstract = _clean_abstract(item.get("abstract", ""))
        combined = title + " " + abstract

        if bc_filter and not _passes_prescreen(combined):
            continue   # definitely not oncology — skip before LLM

        candidates.append((title, abstract))
        raw_map.append(item)

    if not candidates:
        return []

    # LLM classification (one batched API call)
    disease = journal.get("disease", "breast cancer")
    keep = _llm_filter(candidates, disease=disease)

    articles = []
    for (title, abstract), item, is_bc in zip(candidates, raw_map, keep):
        if not is_bc:
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
    lines.append("> 資料來源：CrossRef API · 以 Claude AI 確認為乳癌相關論文\n")

    for journal_name, articles in results.items():
        if not articles:
            lines.append(f"\n### {journal_name}\n\n_本期未取得相關論文_\n")
            continue

        with_abstract = [a for a in articles if a.abstract_digest]
        without = [a for a in articles if not a.abstract_digest]

        lines.append(f"\n### {journal_name}（{len(articles)} 篇乳癌相關）\n")

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
