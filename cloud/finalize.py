#!/usr/bin/env python3
"""ER Cardio Weekly 雲端版：寫完稿後的機械檢查（PR 前必跑，全部過才准 push）。

  python cloud/finalize.py --blog-repo ../agoodbear.github.io --week 2026-W38

1. sanitize：grade 具名參數 → 位置參數（W30–W33、W36 兩次炸站的根因）
2. front matter：YAML 合法、slug/week、date、必要欄位、picked = Tier-2 卡數
3. zhtw-mcp lint（大陸用語／簡體字）：有 error 級問題 → 失敗
4. hugo --renderToMemory 整站 build：失敗 → 失敗
exit 0 = 全過；非 0 = 有問題，stdout 會列出要修的地方。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from datetime import datetime

REQUIRED = ["title", "subtitle", "shortTitle", "slug", "week", "weekRange", "date",
            "scanned", "picked", "practiceChanges", "sections"]


SHORTCODE_FIXES = [
    # {{< grade "文字" kind="retro" >}}  →  {{< grade "文字" "retro" >}}
    (re.compile(r'(\{\{<\s*grade\s+"[^"]*")\s+kind="([^"]*)"'), r'\1 "\2"',
     'grade kind= 具名參數 → 位置參數'),
]


def sanitize_shortcodes(content: str) -> tuple[str, list[str]]:
    """回傳 (修正後內容, 修正說明清單)。"""
    fixes = []
    for pat, repl, desc in SHORTCODE_FIXES:
        content, n = pat.subn(repl, content)
        if n:
            fixes.append(f"{desc} ×{n}")
    return content, fixes


def validate_front_matter(article: str, week_label: str) -> list[str]:
    """解析 YAML，缺欄位、錯週次或空白正文一律擋下。"""
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", article, re.S)
    if not match:
        return ["missing or unclosed front matter"]
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [f"invalid YAML: {exc}"]
    if not isinstance(data, dict):
        return ["front matter must be a mapping"]
    problems = []
    if data.get("slug") != week_label:
        problems.append(f"slug != {week_label}")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        problems.append("missing or empty title")
    try:
        datetime.fromisoformat(str(data.get("date", "")))
    except ValueError:
        problems.append("missing or invalid date")
    if not article[match.end():].strip():
        problems.append("empty article body")
    return problems


def extra_checks(article: str, week_label: str) -> list[str]:
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---", article, re.S)
    data = yaml.safe_load(m.group(1)) if m else {}
    problems = [f"缺欄位 {k}" for k in REQUIRED if k not in (data or {})]
    if not data:
        return problems
    if data.get("week") != week_label:
        problems.append(f"week != {week_label}")
    pcs = data.get("practiceChanges") or []
    if not 3 <= len(pcs) <= 5:
        problems.append(f"practiceChanges 應 3–5 條，現在 {len(pcs)}")
    cards = re.findall(r"^## .*\{#s\d+\}", article, re.M)
    if data.get("picked") != len(cards):
        problems.append(f"picked={data.get('picked')} 但 Tier-2 卡（## … {{#sN}}）有 {len(cards)} 張")
    if "kind=" in article and "grade" in article and re.search(r'grade\s+"[^"]*"\s+kind=', article):
        problems.append("仍有 grade kind= 具名參數")
    if "x.com" in article.lower() or "twitter.com" in article.lower():
        problems.append("讀者版面出現 X.com／twitter 連結（規則禁止）")
    return problems


def zhtw_lint(path: Path) -> tuple[bool, str]:
    exe = shutil.which("zhtw-mcp")
    if not exe:
        return True, "zhtw-mcp 不在 PATH，略過（PR 內文要註明）"
    r = subprocess.run([exe, "lint", str(path), "--content-type", "markdown", "--format", "compact"],
                       capture_output=True, text=True, timeout=180)
    out = (r.stdout + r.stderr).strip()
    has_error = bool(re.search(r":E:", out))
    return not has_error, out[:4000] or "(no output)"


def hugo_build(blog: Path) -> tuple[bool, str]:
    if not shutil.which("hugo"):
        return False, "hugo 不在 PATH（先跑 cloud/setup.sh）"
    r = subprocess.run(["hugo", "--renderToMemory"], cwd=blog, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    ok = r.returncode == 0 and "ERROR" not in out
    return ok, "\n".join(l for l in out.splitlines() if "ERROR" in l or "WARN" in l)[:3000] or out[-800:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-repo", required=True)
    ap.add_argument("--week", required=True)
    args = ap.parse_args()
    blog = Path(args.blog_repo).resolve()
    path = blog / "content/er-cardio-weekly" / args.week / "index.md"
    if not path.exists():
        print(f"FAIL 找不到 {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    text, fixes = sanitize_shortcodes(text)
    if fixes:
        path.write_text(text, encoding="utf-8")
        print(f"sanitize 自動修正：{fixes}")
    failed = False
    probs = validate_front_matter(text, args.week) + extra_checks(text, args.week)
    for p in probs:
        print(f"FAIL front matter／結構：{p}")
    failed |= bool(probs)
    ok, out = zhtw_lint(path)
    print(f"{'PASS' if ok else 'FAIL'} zhtw lint\n{out}")
    failed |= not ok
    ok, out = hugo_build(blog)
    print(f"{'PASS' if ok else 'FAIL'} hugo build\n{out}")
    failed |= not ok
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
