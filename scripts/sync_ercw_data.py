#!/usr/bin/env python3
"""把 4 層來源 cache 整理成 Hugo data files。

讀：
  data/webscrape_cache.json
  data/authors_cache.json
  data/journals_cache.json
  (L4 X.com 從 SQLite db.sqlite 讀，若沒 setup 就空陣列)

寫：
  ~/Documents/GitHub/agoodbear.github.io/data/er-cardio-weekly/sources.json

格式：
{
  "generatedAt": "2026-04-29T15:00:00+08:00",
  "blog": [{title, source, url, published, summary, tags}, ...],
  "authors": [{title, author, journal, published, abstract, url, pmid, tags}, ...],
  "journals": [{title, journal, doi, authors, published, abstract, url, tags}, ...],
  "x":      [{handle, content, posted, url}, ...]
}
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUGO_DATA = Path.home() / "Documents/GitHub/agoodbear.github.io/data/er-cardio-weekly"
HUGO_DATA.mkdir(parents=True, exist_ok=True)

TZ_TPE = timezone(timedelta(hours=8))


def load_cache(name: str) -> dict:
    p = ROOT / "data" / f"{name}_cache.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def flatten_webscrape() -> list[dict]:
    """L1：每來源每文一 row，以發布日期降序"""
    cache = load_cache("webscrape")
    out = []
    for source, articles in cache.items():
        for a in articles:
            out.append({
                "title": a.get("title", ""),
                "source": source,
                "url": a.get("url", ""),
                "published": a.get("published") or "",
                "summary": (a.get("summary") or "")[:300],
                "tags": a.get("tags", [])[:5],
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def flatten_authors() -> list[dict]:
    """L2：去重後的 PubMed 文章（同一篇被多位作者匹配只收一次）"""
    cache = load_cache("authors")
    seen_pmid = set()
    out = []
    for matched_author, articles in cache.items():
        for a in articles:
            pmid = a.get("pmid", "")
            if pmid and pmid in seen_pmid:
                continue
            seen_pmid.add(pmid)
            out.append({
                "title": a.get("title", ""),
                "matchedAuthor": matched_author,
                "authors": a.get("authors", []),
                "journal": a.get("journal", ""),
                "published": a.get("published") or "",
                "abstract": (a.get("abstract_digest") or "")[:400],
                "url": a.get("url", ""),
                "pmid": pmid,
                "authorTag": a.get("author_tag", ""),
                "tags": a.get("tags", [])[:5],
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def flatten_journals() -> list[dict]:
    """L3：CrossRef 期刊文章，每期刊組內降序"""
    cache = load_cache("journals")
    out = []
    for journal_name, articles in cache.items():
        for a in articles:
            out.append({
                "title": a.get("title", ""),
                "journal": journal_name,
                "doi": a.get("doi", ""),
                "authors": a.get("authors", [])[:4],
                "published": a.get("published") or "",
                "abstract": (a.get("abstract_digest") or "")[:400],
                "url": a.get("url", ""),
                "tags": a.get("tags", [])[:5],
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def flatten_twitter() -> list[dict]:
    """L4：從 SQLite 讀 tweets（若 db 不存在或空就回空陣列）"""
    db_path = ROOT / "db.sqlite"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT handle, text, posted_at, url FROM tweets ORDER BY posted_at DESC LIMIT 200"
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "handle": r[0],
                "content": (r[1] or "")[:300],
                "posted": r[2] or "",
                "url": r[3] or "",
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def main():
    payload = {
        "generatedAt": datetime.now(TZ_TPE).isoformat(timespec="seconds"),
        "blog": flatten_webscrape(),
        "authors": flatten_authors(),
        "journals": flatten_journals(),
        "x": flatten_twitter(),
    }
    out_file = HUGO_DATA / "sources.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"✓ wrote {out_file}")
    print(
        f"  blog: {len(payload['blog'])} / authors: {len(payload['authors'])} "
        f"/ journals: {len(payload['journals'])} / x: {len(payload['x'])}"
    )


if __name__ == "__main__":
    main()
