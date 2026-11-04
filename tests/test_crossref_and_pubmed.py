"""L2 PubMed / L3 CrossRef 解析。全部用假資料，不連網。"""
import asyncio

import httpx

from src import author_fetcher as af
from src import crossref_fetcher as cf


# ── CrossRef ─────────────────────────────────────────────────────────────────

def test_pub_date_variants():
    assert cf._pub_date({"published": {"date-parts": [[2026, 9, 7]]}}) == "2026-09-07"
    assert cf._pub_date({"published-print": {"date-parts": [[2026, 9]]}}) == "2026-09"
    assert cf._pub_date({"published-online": {"date-parts": [[2026]]}}) == "2026"
    assert cf._pub_date({}) is None


def test_pub_date_null_parts_does_not_crash():
    # CrossRef 偶爾回 {"date-parts": [[null]]}；以前會 TypeError 讓整本期刊丟失
    assert cf._pub_date({"published": {"date-parts": [[None]]}}) is None
    assert cf._pub_date({"published": {"date-parts": [[2026, None, None]]}}) == "2026"


def test_prescreen_word_boundary():
    assert cf._passes_prescreen("Brugada pattern unmasked by fever")
    assert cf._passes_prescreen("Outcomes after VT ablation")
    assert not cf._passes_prescreen("Heart failure with preserved ejection fraction outcomes")
    assert not cf._passes_prescreen("pivotal results")   # "VT" 不可吃到 pivotal


def test_clean_abstract_strips_jats():
    raw = "<jats:p>Background <jats:italic>ECG</jats:italic>\n  text</jats:p>"
    assert cf._clean_abstract(raw) == "Background ECG text"


def test_digest_abstract_prefers_signal_sentences_and_respects_limit():
    abstract = ("This is background. " * 5 +
                "Mortality was significantly reduced (HR 0.70, 95% CI 0.6-0.8). "
                "We thank the nurses.")
    d = cf._digest_abstract(abstract, max_chars=120)
    assert d.startswith("Mortality was significantly reduced")
    assert len(d) <= 120
    assert cf._digest_abstract("") == ""


CROSSREF_JSON = {"message": {"items": [
    {"DOI": "10.1/ecg1", "title": ["Wellens syndrome in the ED: a series"],
     "author": [{"family": f"A{i}", "given": "Bob"} for i in range(6)],
     "published": {"date-parts": [[2026, 10, 1]]}, "container-title": ["Heart Rhythm"],
     "abstract": "<jats:p>12-lead ECG findings.</jats:p>"},
    {"DOI": "10.1/hf", "title": ["Valve surgery outcomes in heart failure"],
     "published": {"date-parts": [[2026, 10, 1]]}},
]}}


def test_fetch_journal_parses_and_filters():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=CROSSREF_JSON)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await cf._fetch_journal(c, {"name": "HR", "issn": "1547-5271"}, "me@example.org")

    arts = asyncio.run(go())
    assert len(calls) == 1 and "mailto:me@example.org" in calls[0].headers["User-Agent"]
    assert [a.doi for a in arts] == ["10.1/ecg1"]
    a = arts[0]
    assert a.url == "https://doi.org/10.1/ecg1"
    assert a.authors[-1] == "et al." and len(a.authors) == 5
    assert a.journal == "Heart Rhythm"


# ── PubMed ───────────────────────────────────────────────────────────────────

def _article(pmid, title, abstract, n_authors, pubdate="<Year>2026</Year><Month>Sep</Month><Day>7</Day>"):
    authors = "".join(f"<Author><LastName>L{i}</LastName><Initials>X</Initials></Author>"
                      for i in range(n_authors))
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
      <Journal><Title>J Electrocardiol</Title><JournalIssue><PubDate>{pubdate}</PubDate></JournalIssue></Journal>
      <ArticleTitle>{title}</ArticleTitle>
      <Abstract><AbstractText Label="RESULTS">{abstract}</AbstractText></Abstract>
      <AuthorList>{authors}</AuthorList></Article></MedlineCitation></PubmedArticle>"""


def _set(*arts):
    return "<PubmedArticleSet>" + "".join(arts) + "</PubmedArticleSet>"


def test_parse_efetch_filters_non_ecg_and_builds_url():
    xml = _set(_article("111", "OMI vs STEMI criteria", "ECG accuracy improved.", 2),
               _article("222", "Hip fracture rehab", "Nothing cardiac.", 2))
    arts = af._parse_efetch_xml(xml, "Smith SW", "OMI")
    assert [a.pmid for a in arts] == ["111"]
    a = arts[0]
    assert a.url == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert a.published == "2026-09-07"
    assert a.abstract.startswith("RESULTS: ")
    assert a.matched_author == "Smith SW" and a.author_tag == "OMI"


def test_parse_authors_exactly_four_has_no_et_al():
    # 以前剛好 4 位作者也會被加上 "et al."
    xml = _set(_article("1", "ECG paper", "ECG", 4))
    assert af._parse_efetch_xml(xml, "", "")[0].authors == ["L0 X", "L1 X", "L2 X", "L3 X"]


def test_parse_authors_more_than_four_gets_et_al():
    xml = _set(_article("1", "ECG paper", "ECG", 7))
    assert af._parse_efetch_xml(xml, "", "")[0].authors == ["L0 X", "L1 X", "L2 X", "L3 X", "et al."]


def test_parse_pubdate_medline_and_season_fallbacks():
    xml = _set(_article("1", "ECG a", "ECG", 1, "<MedlineDate>2026 Sep-Oct</MedlineDate>"))
    assert af._parse_efetch_xml(xml, "", "")[0].published is None
    xml = _set(_article("1", "ECG a", "ECG", 1, "<Year>2026</Year><Season>Spring</Season>"))
    assert af._parse_efetch_xml(xml, "", "")[0].published == "2026-01-01"


def test_parse_efetch_garbage():
    assert af._parse_efetch_xml("", "", "") == []
    assert af._parse_efetch_xml("<not-closed", "", "") == []


def test_fetch_one_author_esearch_then_efetch():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("esearch.fcgi"):
            assert request.url.params["reldate"] == "14"
            return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
        return httpx.Response(200, text=_set(_article("111", "ECG thing", "ECG", 1)))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await af._fetch_one_author(c, {"name": "N", "query": "Smith SW[au]"}, "e@x")

    arts = asyncio.run(go())
    assert [p.rsplit("/", 1)[-1] for p in seen] == ["esearch.fcgi", "efetch.fcgi"]
    assert [a.pmid for a in arts] == ["111"]
