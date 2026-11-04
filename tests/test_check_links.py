"""scripts/check_links.py：擷取、政策跳過、Text Fragment、站內檢查。不連網。"""
import asyncio

import httpx

from conftest import load_script

cl = load_script("scripts/check_links.py", "check_links")


def test_extract_from_html_kinds():
    html = """<html><head>
      <link rel="icon" href="/icons/favicon.png"><link rel="stylesheet" href="/css/a.css">
      <meta property="og:image" content="https://cdn.example.org/og.png">
      <script src="/js/x.js"></script></head><body>
      <a href="https://doi.org/10.1/x#:~:text=hello">r</a>
      <img src="ecg.png" srcset="ecg-2x.png 2x, ecg-3x.png 3x">
      <a href="#fn1">1</a></body></html>"""
    got = set(cl.extract_from_html(html))
    assert ("/icons/favicon.png", "icon") in got
    assert ("/css/a.css", "stylesheet") in got
    assert ("https://cdn.example.org/og.png", "meta-image") in got
    assert ("/js/x.js", "script") in got
    assert ("ecg.png", "image") in got and ("ecg-3x.png", "image") in got
    assert ("https://doi.org/10.1/x#:~:text=hello", "link") in got


def test_extract_from_text_skips_placeholders_and_trims_punct():
    text = """見 https://pubmed.ncbi.nlm.nih.gov/12345/。
    範例 https://drsmithsecgblog.com/.../#:~:text=x 與 https://pubmed.ncbi.nlm.nih.gov/{pmid}/
    API https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=
    ![ECG](https://img.example.org/a.png) 以及 [link](https://litfl.com/wellens/)
    {{< figure-ecg src="local.png" alt="x" >}}"""
    got = dict(cl.extract_from_text(text))
    assert got["https://pubmed.ncbi.nlm.nih.gov/12345/"] == "link"
    assert got["https://img.example.org/a.png"] == "image"
    assert got["https://litfl.com/wellens/"] == "link"
    assert got["local.png"] == "image"
    assert not any("..." in u or "{" in u or u.endswith("=") for u in got)


def test_host_policy_never_fetches_ecgweekly_or_x():
    assert cl.host_policy("https://ecgweekly.com/weekly-workout/x")
    assert cl.host_policy("https://www.ecgweekly.com/")
    assert cl.host_policy("https://x.com/smithECGBlog/status/1")
    assert cl.host_policy("https://mobile.twitter.com/a")
    assert cl.host_policy("https://notecgweekly.com/") is None
    assert cl.host_policy("https://doi.org/10.1/x") is None


def test_parse_text_fragment_variants():
    f = cl.parse_text_fragment
    assert f("https://a.org/p#:~:text=hello%20world") == "hello world"
    assert f("https://a.org/p#:~:text=pre-,start%20here,end,-suf") == "start here"
    assert f("https://a.org/p#sec:~:text=x") == "x"
    assert f("https://a.org/p#plain") is None
    assert f("https://a.org/p") is None


def test_fragment_in_text_normalises_quotes_and_space():
    page = "He said “the  ECG was   normal” — really."
    assert cl.fragment_in_text('"the ECG was normal"', page)
    assert not cl.fragment_in_text("abnormal ST", page)


def test_classify():
    assert cl.classify(200, None) == "OK"
    assert cl.classify(301, None) == "OK"
    assert cl.classify(404, None) == "BROKEN"
    assert cl.classify(410, None) == "BROKEN"
    assert cl.classify(403, None) == "BLOCKED"
    assert cl.classify(429, None) == "BLOCKED"
    assert cl.classify(500, None) == "ERROR"
    assert cl.classify(None, "ConnectError") == "ERROR"


def test_check_internal(tmp_path):
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "a.css").write_text("x")
    (tmp_path / "w" / "2026-w44").mkdir(parents=True)
    (tmp_path / "w" / "2026-w44" / "index.html").write_text("x")
    assert cl.check_internal("/css/a.css?v=1", tmp_path, "w/2026-w44")[0]
    assert cl.check_internal("/w/2026-w44/", tmp_path, "")[0]
    # GitHub Pages 大小寫敏感：W44 ≠ w44
    assert not cl.check_internal("/w/2026-W44/", tmp_path, "")[0]
    # 主題 footer 把 "@handle" 當 href 的那種相對路徑
    ok, note = cl.check_internal("@ED_Ultrasounder", tmp_path, "w/2026-w44")
    assert not ok and "@ED_Ultrasounder" in note


def test_check_external_skips_policy_hosts_and_dedupes(monkeypatch):
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if "gone" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, text="<p>The ECG was normal</p>",
                              headers={"content-type": "text/html"})

    real_client = httpx.AsyncClient

    def fake_client(**kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    links = [
        cl.Link("https://ecgweekly.com/weekly-workout/a", "link", ["/p/"]),
        cl.Link("https://ok.org/a#:~:text=ECG%20was%20normal", "link", ["/p/"]),
        cl.Link("https://ok.org/a#:~:text=not%20there", "link", ["/q/"]),
        cl.Link("https://ok.org/gone", "link", ["/p/"]),
    ]
    res = {r.url: r for r in asyncio.run(cl.check_external(links, check_fragments=True))}
    assert res["https://ecgweekly.com/weekly-workout/a"].status == "SKIPPED"
    assert not any("ecgweekly" in u for _, u in calls)
    assert res["https://ok.org/a#:~:text=ECG%20was%20normal"].fragment_found is True
    assert res["https://ok.org/a#:~:text=not%20there"].fragment_found is False
    assert res["https://ok.org/gone"].status == "BROKEN"
    # 同一個 base URL（不同 fragment）只 GET 一次
    assert sum(1 for m, u in calls if u == "https://ok.org/a") == 1


def test_to_markdown_summary():
    rs = [cl.Result("https://a", "link", "OK", 200), cl.Result("https://b", "image", "BROKEN", 404, sources=["/p/"])]
    md = cl.to_markdown(rs)
    assert "| BROKEN | 1 |" in md and "| OK | 1 |" in md and "`https://b`" in md


def _mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def fake_client(**kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def test_redirect_into_forbidden_host_is_never_requested(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "short.example.org":
            return httpx.Response(302, headers={"location": "https://www.ecgweekly.com/weekly-workout/x"})
        if request.url.host == "hop.example.org" and request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/html"})

    _mock_client(monkeypatch, handler)
    links = [cl.Link("https://short.example.org/a", "link", ["/p/"]),
             cl.Link("https://hop.example.org/a", "link", ["/p/"])]
    res = {r.url: r for r in asyncio.run(cl.check_external(links, check_fragments=False))}
    assert not any("ecgweekly" in u for u in calls), calls
    r = res["https://short.example.org/a"]
    assert r.status == "SKIPPED" and "ecgweekly" in r.note
    ok = res["https://hop.example.org/a"]
    assert ok.status == "OK" and ok.final_url == "https://hop.example.org/final"


def test_redirect_loop_is_reported(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(302, headers={"location": str(r.url)}))
    res = asyncio.run(cl.check_external([cl.Link("https://loop.example.org/", "link", [])], False))
    assert res[0].status == "REDIRECT_LOOP"


def test_protocol_relative_urls_are_treated_as_external(tmp_path):
    page = tmp_path / "er-cardio-weekly" / "2026-w44"
    page.mkdir(parents=True)
    (page / "index.html").write_text(
        '<link rel="stylesheet" href="//cdn.example.org/a.css">'
        '<a href="//ecgweekly.com/x">e</a>')
    links, internal = cl.collect(tmp_path, "er-cardio-weekly", [], tmp_path)
    assert internal == []
    assert ("https://cdn.example.org/a.css", "stylesheet") in links
    assert cl.host_policy(links[("https://ecgweekly.com/x", "link")].url)
