#!/usr/bin/env python3
"""檢查週報（與本 repo 文件）裡的外部連結、圖片連結有沒有壞掉。

只讀不寫：不改任何內容，只輸出報告。

用法：
  # 1) 先把部落格 build 到某個資料夾（不部署）
  hugo --source <agoodbear.github.io> --destination /tmp/site
  # 2) 掃描 build 結果裡的週報頁面 + 本 repo 的 markdown / yml
  uv run python scripts/check_links.py \
      --site-root /tmp/site --section er-cardio-weekly \
      --files README.md CLAUDE.md reports/*.md source/*.yml cloud/ROUTINE.md \
      --check-fragments --json out.json --md out.md

政策（寫死，不可用參數關掉）：
  - ecgweekly.com 一律不連線（2026-10-05 帳號曾因自動化存取被鎖；見 cloud/ROUTINE.md）。
  - x.com / twitter.com 需要登入，匿名結果不可信 → 不連線，標 SKIPPED。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

from bs4 import BeautifulSoup

# ── 政策 ──────────────────────────────────────────────────────────────────────
NEVER_FETCH = {
    "ecgweekly.com": "政策禁止連線（ECG Weekly 偵測自動化會鎖帳號）",
    "x.com": "需登入，匿名檢查不可信",
    "twitter.com": "需登入，匿名檢查不可信",
}

URL_RE = re.compile(r"https?://[^\s<>\"'`)\]}|]+")
# 模板/範例裡的假網址（例如 SOP 裡的 "https://drsmithsecgblog.com/.../"）不檢查
PLACEHOLDER_RE = re.compile(r"/\.\.\.|\.\.\./|<[^>]*>|\{|\bYYYY\b|WNN|example\.com|[=&]$")
TRAILING_PUNCT = ".,;:!?。，、；：！？」』）"


@dataclass
class Link:
    url: str
    kind: str                     # link | image | stylesheet | script | icon | meta-image
    sources: list[str] = field(default_factory=list)   # 出現在哪些頁面/檔案


@dataclass
class Result:
    url: str
    kind: str
    status: str                   # OK | BROKEN | BLOCKED | ERROR | SKIPPED | REDIRECT_LOOP
    http_status: int | None = None
    final_url: str | None = None
    note: str = ""
    fragment: str | None = None   # Text Fragment 的 textStart（若有）
    fragment_found: bool | None = None
    sources: list[str] = field(default_factory=list)


# ── 擷取 ──────────────────────────────────────────────────────────────────────

def _clean_url(u: str) -> str:
    u = u.strip()
    while u and u[-1] in TRAILING_PUNCT:
        u = u[:-1]
    # 成對括號：markdown 外 regex 抓到 "...(foo)" 時保留，孤立的 ")" 已被 URL_RE 排除
    return u


def extract_from_html(html: str) -> list[tuple[str, str]]:
    """回傳 [(url, kind)]。包含站內絕對路徑（/css/...）與外部 http(s)。"""
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        out.append((a["href"], "link"))
    for img in soup.find_all("img"):
        if img.get("src"):
            out.append((img["src"], "image"))
        for part in (img.get("srcset") or "").split(","):
            part = part.strip().split(" ")[0]
            if part:
                out.append((part, "image"))
    for src in soup.find_all("source"):
        for part in (src.get("srcset") or "").split(","):
            part = part.strip().split(" ")[0]
            if part:
                out.append((part, "image"))
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "stylesheet" in rel:
            out.append((link["href"], "stylesheet"))
        elif "icon" in rel:
            out.append((link["href"], "icon"))
    for s in soup.find_all("script", src=True):
        out.append((s["src"], "script"))
    for m in soup.find_all("meta"):
        prop = (m.get("property") or m.get("name") or "").lower()
        if prop in ("og:image", "twitter:image") and m.get("content"):
            out.append((m["content"], "meta-image"))
    return [(u.strip(), k) for u, k in out if u and u.strip()]


MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
SHORTCODE_SRC_RE = re.compile(r'\{\{<\s*figure-ecg[^>]*\bsrc="([^"]+)"')


def extract_from_text(text: str) -> list[tuple[str, str]]:
    """Markdown / YAML / 純文字：抓 http(s) 網址；markdown 圖片與 figure-ecg 的 src 標成 image。"""
    images = {m.group(1) for m in MD_IMAGE_RE.finditer(text)}
    images |= {m.group(1) for m in SHORTCODE_SRC_RE.finditer(text)}
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in URL_RE.finditer(text):
        u = _clean_url(m.group(0))
        if PLACEHOLDER_RE.search(u) or u in seen:
            continue
        seen.add(u)
        out.append((u, "image" if u in images else "link"))
    for u in images:
        if not u.startswith("http") and u not in seen:
            out.append((u, "image"))
    return out


def is_external(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def host_policy(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for h, why in NEVER_FETCH.items():
        if host == h or host.endswith("." + h):
            return why
    return None


# ── Text Fragment ─────────────────────────────────────────────────────────────

def parse_text_fragment(url: str) -> str | None:
    """'...#:~:text=prefix-,start,end,-suffix' → 'start'（已解碼）。沒有就回 None。"""
    _, frag = urldefrag(url)
    if ":~:" not in frag:
        return None
    directive = frag.split(":~:", 1)[1]
    for part in directive.split("&"):
        if not part.startswith("text="):
            continue
        pieces = part[len("text="):].split(",")
        # 去掉 prefix-（結尾為 -）與 -suffix（開頭為 -）
        pieces = [p for p in pieces if not p.endswith("-") and not p.startswith("-")]
        if pieces:
            return unquote(pieces[0])
    return None


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace(" ", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def fragment_in_text(fragment: str, page_text: str) -> bool:
    return _norm(fragment) in _norm(page_text)


# ── 站內檢查 ──────────────────────────────────────────────────────────────────

def _exact_case(p: Path, root: Path) -> bool:
    """macOS 預設檔案系統不分大小寫；逐層比對實際檔名，確保跟 GitHub Pages 一樣大小寫敏感。"""
    try:
        rel = p.relative_to(root)
    except ValueError:
        return True
    cur = root
    for part in rel.parts:
        if part in ("", "."):
            continue
        if part == "..":
            cur = cur.parent
            continue
        try:
            names = {e.name for e in cur.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        cur = cur / part
    return True


def check_internal(url: str, site_root: Path, page_rel_dir: str) -> tuple[bool, str]:
    """站內路徑（/x/y 或相對路徑）是否存在於 build 結果。大小寫敏感（GitHub Pages 也是）。"""
    path = urlparse(url).path
    if not path:
        return True, "同頁錨點"
    if path.startswith("/"):
        target = site_root / unquote(path).lstrip("/")
    else:
        target = site_root / page_rel_dir / unquote(path)
    candidates = [target, target / "index.html"]
    if not target.suffix:
        candidates.append(target.with_suffix(".html"))
    for c in candidates:
        if c.is_file() and _exact_case(c, site_root):
            return True, ""
    return False, f"build 結果找不到 {target.relative_to(site_root) if site_root in target.parents else target}"


# ── 外部檢查 ──────────────────────────────────────────────────────────────────

def classify(http_status: int | None, error: str | None) -> str:
    if error:
        return "ERROR"
    if http_status is None:
        return "ERROR"
    if 200 <= http_status < 400:
        return "OK"
    if http_status in (404, 410):
        return "BROKEN"
    if http_status in (401, 403, 429, 999) or http_status in (503,):
        return "BLOCKED"   # 多半是防爬／限流，不代表連結壞；需人工點開確認
    return "BROKEN" if 400 <= http_status < 500 else "ERROR"


class PolicyRedirect(Exception):
    """轉址目的地落在 NEVER_FETCH 名單：不發出請求。"""


MAX_REDIRECTS = 10


async def _request(client, method: str, url: str):
    """手動跟轉址：每一跳發請求「之前」都先過 host_policy，
    避免允許的網址 302 到 ecgweekly.com／x.com 時被自動打過去。"""
    import httpx

    for _ in range(MAX_REDIRECTS + 1):
        why = host_policy(url)
        if why:
            raise PolicyRedirect(f"轉址到 {urlparse(url).hostname}：{why}")
        r = await client.request(method, url)
        location = r.headers.get("location")
        if r.status_code in (301, 302, 303, 307, 308) and location:
            url = urldefrag(str(r.url.join(location)))[0]
            if r.status_code == 303:
                method = "GET"
            continue
        return r
    raise httpx.TooManyRedirects("too many redirects", request=r.request)


async def _fetch_one(client, url: str, want_text: bool) -> tuple[int | None, str | None, str | None, str | None]:
    """回傳 (status, final_url, body_text_or_None, error)。先 HEAD，不行再 GET。"""
    import httpx

    target, _ = urldefrag(url)
    try:
        if not want_text:
            r = await _request(client, "HEAD", target)
            if r.status_code < 400:
                return r.status_code, str(r.url), None, None
        r = await _request(client, "GET", target)
        body = None
        ctype = r.headers.get("content-type", "")
        if want_text and r.status_code < 400 and "html" in ctype:
            body = r.text
        return r.status_code, str(r.url), body, None
    except PolicyRedirect as e:
        return None, None, None, f"policy-redirect: {e}"
    except httpx.TooManyRedirects:
        return None, None, None, "too many redirects"
    except Exception as e:  # noqa: BLE001 — 任何網路錯誤都要記錄，不中斷整批
        return None, None, None, f"{type(e).__name__}: {e}"[:200]


async def check_external(links: list[Link], check_fragments: bool, concurrency: int = 8,
                         per_host: int = 2, timeout: float = 25.0) -> list[Result]:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36 ercw-linkcheck",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    sem = asyncio.Semaphore(concurrency)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(per_host))
    # 同一個去掉 fragment 的網址只打一次
    cache: dict[tuple[str, bool], asyncio.Task] = {}

    # follow_redirects=False：轉址由 _request 手動處理，才能逐跳檢查政策
    async with httpx.AsyncClient(headers=headers, follow_redirects=False, timeout=timeout) as client:

        async def fetch(base: str, want_text: bool):
            host = urlparse(base).hostname or ""
            async with sem, host_sems[host]:
                res = await _fetch_one(client, base, want_text)
                await asyncio.sleep(0.3)   # 禮貌間隔
                return res

        def get_task(base: str, want_text: bool) -> asyncio.Task:
            key = (base, want_text)
            if key not in cache:
                cache[key] = asyncio.ensure_future(fetch(base, want_text))
            return cache[key]

        async def one(link: Link) -> Result:
            why = host_policy(link.url)
            frag = parse_text_fragment(link.url)
            if why:
                return Result(link.url, link.kind, "SKIPPED", note=why, fragment=frag,
                              sources=link.sources)
            base, _ = urldefrag(link.url)
            want_text = bool(check_fragments and frag)
            status, final, body, err = await get_task(base, want_text)
            res = Result(link.url, link.kind, classify(status, err), status, final,
                         err or "", frag, None, link.sources)
            if err and err.startswith("policy-redirect"):
                res.status, res.note = "SKIPPED", err
            elif err and "redirect" in err:
                res.status = "REDIRECT_LOOP"
            if want_text and body is not None:
                text = BeautifulSoup(body, "lxml").get_text(" ")
                res.fragment_found = fragment_in_text(frag, text)
            return res

        return await asyncio.gather(*(one(l) for l in links))


# ── 主流程 ────────────────────────────────────────────────────────────────────

def collect(site_root: Path | None, section: str | None, files: list[Path],
            repo_root: Path) -> tuple[dict[tuple[str, str], Link], list[Result]]:
    links: dict[tuple[str, str], Link] = {}
    internal_results: list[Result] = []

    def add(url: str, kind: str, src: str):
        key = (url, kind)
        if key not in links:
            links[key] = Link(url, kind)
        if src not in links[key].sources:
            links[key].sources.append(src)

    if site_root and section:
        for page in sorted((site_root / section).glob("*/index.html")):
            rel_dir = str(page.parent.relative_to(site_root))
            src = "/" + rel_dir + "/"
            for url, kind in extract_from_html(page.read_text(encoding="utf-8")):
                if url.startswith("//"):          # protocol-relative → 當外部 https 處理
                    url = "https:" + url
                if url.startswith(("mailto:", "tel:", "javascript:", "data:")) or url.startswith("#"):
                    continue
                if is_external(url):
                    add(url, kind, src)
                else:
                    ok, note = check_internal(url, site_root, rel_dir)
                    if not ok:
                        internal_results.append(Result(url, kind, "BROKEN", note=note, sources=[src]))
    for f in files:
        try:
            rel = str(f.resolve().relative_to(repo_root))
        except ValueError:
            rel = str(f)
        text = f.read_text(encoding="utf-8")
        for url, kind in extract_from_text(text):
            if is_external(url):
                add(url, kind, rel)
            elif kind == "image":
                ok = (f.parent / url).is_file()
                if not ok:
                    internal_results.append(Result(url, kind, "BROKEN", note="圖片檔不存在", sources=[rel]))
    return links, internal_results


def to_markdown(results: list[Result]) -> str:
    order = ["BROKEN", "REDIRECT_LOOP", "ERROR", "BLOCKED", "SKIPPED", "OK"]
    counts = defaultdict(int)
    for r in results:
        counts[r.status] += 1
    lines = ["| 狀態 | 數量 |", "|---|---|"]
    lines += [f"| {s} | {counts[s]} |" for s in order if counts[s]]
    frag_bad = [r for r in results if r.fragment_found is False]
    lines.append(f"| Text Fragment 找不到原句 | {len(frag_bad)} |")
    lines.append("")
    for s in order[:-1]:
        rows = [r for r in results if r.status == s]
        if not rows:
            continue
        lines += [f"### {s}（{len(rows)}）", "", "| URL | 類型 | HTTP | 說明 | 出現於 |", "|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: r.url):
            lines.append(f"| `{r.url[:140]}` | {r.kind} | {r.http_status or '—'} | "
                         f"{(r.note or '').replace('|', '／')[:80]} | {', '.join(r.sources[:4])}"
                         f"{' …' if len(r.sources) > 4 else ''} |")
        lines.append("")
    if frag_bad:
        lines += ["### Text Fragment 在原文找不到（頁面 200，但 `#:~:text=` 句子不在 HTML 文字中）", "",
                  "| URL（去掉 fragment） | 找不到的句子 | 出現於 |", "|---|---|---|"]
        for r in sorted(frag_bad, key=lambda r: r.url):
            lines.append(f"| `{urldefrag(r.url)[0][:120]}` | {r.fragment[:80]} | {', '.join(r.sources[:3])} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-root", type=Path, help="hugo build 輸出資料夾")
    ap.add_argument("--section", default="er-cardio-weekly")
    ap.add_argument("--files", nargs="*", type=Path, default=[])
    ap.add_argument("--check-fragments", action="store_true", help="GET 頁面並確認 #:~:text= 句子存在")
    ap.add_argument("--offline", action="store_true", help="只做擷取與站內檢查，不連外")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    links, internal = collect(args.site_root, args.section, args.files, repo_root)
    print(f"擷取：外部 {len(links)} 筆（url×類型）、站內壞連結 {len(internal)} 筆", file=sys.stderr)
    external: list[Result] = []
    if not args.offline:
        external = asyncio.run(check_external(list(links.values()), args.check_fragments))
    results = internal + external
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    md = to_markdown(results)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    else:
        print(md)
    return 1 if any(r.status in ("BROKEN", "REDIRECT_LOOP") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
