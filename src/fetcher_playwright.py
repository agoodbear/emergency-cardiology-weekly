"""Playwright-based X.com fetcher.

twscrape (PyPI v0.17.0 + community PR forks) 對最新 X 反爬機制全部失效
（main.js chunk loader pattern 改了，XClIdGen 永遠 fail）。改用 Playwright
直接驅動 headless Chromium 載入 x.com，攔截 GraphQL XHR response 解析推文。

走「User Profile」路線（不走 search）：直接 visit `https://x.com/{handle}`，
攔截 `UserTweets` GraphQL response，解 legacy.full_text 等欄位。比 search
穩定（search endpoint op_id 會 rotate，UserTweets 比較固定）。
"""

import asyncio
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext
from rich.console import Console
from . import db, config

console = Console()

ROOT = Path(__file__).parent.parent
SEEDS_FILE = ROOT / "config" / "seeds.txt"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _load_seeds() -> list[str]:
    handles = []
    for line in SEEDS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        handle = line.split("#")[0].strip().split()[0]
        if handle:
            handles.append(handle)
    return handles


async def _setup_context(playwright, auth_token: str, ct0: str) -> tuple:
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    await context.add_cookies([
        {
            "name": "auth_token",
            "value": auth_token,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
        },
        {
            "name": "ct0",
            "value": ct0,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax",
        },
    ])
    return browser, context


def _twitter_date_to_iso(s: str) -> str:
    """X 推文的 created_at 是 'Wed Apr 29 14:48:08 +0000 2026' 這種 RFC 2822 變體；
    SQLite 的 datetime('now') 比較需要 ISO 8601。"""
    if not s:
        return ""
    try:
        return parsedate_to_datetime(s).isoformat()
    except Exception:
        return s


def _parse_tweet_node(tw: dict) -> dict | None:
    """從 X GraphQL Tweet node（legacy 結構）解出 DB 需要的欄位。"""
    legacy = tw.get("legacy") or {}
    rest_id = tw.get("rest_id") or legacy.get("id_str")
    if not rest_id or not legacy.get("full_text"):
        return None
    user_result = (
        tw.get("core", {}).get("user_results", {}).get("result", {})
    )
    user_legacy = user_result.get("legacy") or {}
    user_core = user_result.get("core") or {}
    handle = user_legacy.get("screen_name") or user_core.get("screen_name") or ""
    display_name = user_legacy.get("name") or user_core.get("name") or ""
    return {
        "id": str(rest_id),
        "author": handle,
        "display_name": display_name,
        "bio": user_legacy.get("description", ""),
        "followers": user_legacy.get("followers_count", 0),
        "content": legacy.get("full_text", ""),
        "created_at": _twitter_date_to_iso(legacy.get("created_at", "")),
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "url": f"https://x.com/{handle}/status/{rest_id}" if handle else "",
    }


def _walk_for_tweets(node, out: list):
    """X GraphQL response 是深 nested instructions/entries/content 結構，
    遞迴找所有 __typename == 'Tweet' 的節點。"""
    if isinstance(node, dict):
        if node.get("__typename") == "Tweet" and "rest_id" in node:
            parsed = _parse_tweet_node(node)
            if parsed:
                out.append(parsed)
        # 有些 wrapper：{"tweet": {...Tweet...}} 或 result: {Tweet}
        for v in node.values():
            _walk_for_tweets(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_for_tweets(item, out)


async def _fetch_handle_tweets(
    context: BrowserContext, handle: str, max_tweets: int = 50, scroll_rounds: int = 3
) -> list[dict]:
    """Visit x.com/{handle}, intercept timeline GraphQL responses, parse out tweets."""
    page = await context.new_page()
    captured: list[dict] = []

    # ⚠️ 2026-08-16：X 把個人頁時間軸的 GraphQL operation 從 UserTweets 改名成
    #    UserOriginalsTimeline，舊的名單一個都對不上 → 攔不到任何 response →
    #    「✓ Fetched 0 tweets total」但 exit 0，靜默失敗（8/9 起連壞一週沒被發現）。
    #    實測 payload 內部 schema **沒變**（__typename=='Tweet' + legacy.full_text 都在），
    #    所以只需要放寬 operation 名單，_walk_for_tweets / _parse_tweet_node 不用動。
    #    保留舊名是為了相容——X 改名頻繁，多留幾個不會有副作用。
    TIMELINE_OPS = (
        "/UserOriginalsTimeline",   # 2026-08 現行
        "/UserTweets",              # 舊名，保留
        "/UserTweetsAndReplies",
        "/UserMedia",
    )

    async def on_response(response):
        url = response.url
        if any(op in url for op in TIMELINE_OPS):
            try:
                data = await response.json()
                captured.append(data)
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(
            f"https://x.com/{handle}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        # 等 GraphQL 第一波載入
        await page.wait_for_timeout(3500)
        # 滾動觸發更多分頁載入
        for _ in range(scroll_rounds):
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(1800)
    except Exception as e:
        console.print(f"  [yellow]⚠ {handle} navigation error: {e}[/yellow]")
    finally:
        await page.close()

    tweets: list[dict] = []
    seen = set()
    for data in captured:
        bucket: list[dict] = []
        _walk_for_tweets(data, bucket)
        for tw in bucket:
            if tw["id"] in seen:
                continue
            seen.add(tw["id"])
            tweets.append(tw)

    # 僅保留該 handle 本人的推文（過濾 retweet 別人 / quote tweet 中的 quoted tweet 雜訊）
    tweets = [t for t in tweets if t["author"].lower() == handle.lower()]
    return tweets[:max_tweets]


async def _run_fetch(username: str, email: str, auth_token: str, ct0: str):
    db.init_db()
    handles = _load_seeds()
    console.print(f"\n[cyan]Playwright 模式：抓 {len(handles)} 個 handle 的最新推文[/cyan]")
    console.print(f"  seeds: {', '.join('@' + h for h in handles)}\n")

    total = 0
    async with async_playwright() as pw:
        browser, context = await _setup_context(pw, auth_token, ct0)
        try:
            for i, handle in enumerate(handles, 1):
                console.print(f"[cyan]{i}/{len(handles)}:[/cyan] @{handle}")
                tweets = await _fetch_handle_tweets(context, handle)
                if not tweets:
                    console.print(f"  [yellow]0 tweets[/yellow]")
                    continue
                # 第一筆推文順便 upsert account 資訊
                first = tweets[0]
                db.upsert_account(
                    handle=first["author"],
                    display_name=first.get("display_name", ""),
                    bio=first.get("bio", ""),
                    followers=first.get("followers", 0),
                    discovered_via="seed",
                )
                for tw in tweets:
                    db.upsert_tweet(
                        tweet_id=tw["id"],
                        author=tw["author"],
                        content=tw["content"],
                        created_at=tw["created_at"],
                        likes=tw["likes"],
                        retweets=tw["retweets"],
                        url=tw["url"],
                    )
                total += len(tweets)
                console.print(f"  [green]{len(tweets)} tweets[/green]")
        finally:
            await context.close()
            await browser.close()

    console.print(f"\n[bold green]✓ Fetched {total} tweets total[/bold green]")


def fetch(username: str, email: str, auth_token: str, ct0: str):
    asyncio.run(_run_fetch(username, email, auth_token, ct0))
