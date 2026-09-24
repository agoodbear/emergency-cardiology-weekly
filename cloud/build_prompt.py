#!/usr/bin/env python3
"""ER Cardio Weekly — 雲端版：把 L1/L2/L3 cache 組成寫稿 brief。

由雲端 routine 呼叫（見 cloud/ROUTINE.md）。本機版在 ~/scripts/run-er-cardio-weekly-v2.py，
寫稿規則（build_prompt 的 system 文字）從該檔原樣搬來；改規則時兩邊一起改，
直到本機 launchd 停用為止。

雲端版差異：
  - 不讀 L4 X.com（雲端沒有 X cookie；X 本來就只是線索層）
  - 輸出 brief 檔給 routine 裡的 Claude 讀，不呼叫任何 LLM
用法：
  python cloud/build_prompt.py --blog-repo ../agoodbear.github.io [--week 2026-W38] --out cloud/out/brief.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ERCW_REPO = Path(__file__).resolve().parent.parent
CACHE_FILES = {
    "L1_web": ERCW_REPO / "data/webscrape_cache.json",
    "L2_pubmed": ERCW_REPO / "data/authors_cache.json",
    "L3_crossref": ERCW_REPO / "data/journals_cache.json",
}
CONTENT_BASE: Path  # main() 依 --blog-repo 設定


def log(msg: str) -> None:
    print(f"[build_prompt] {msg}", file=sys.stderr, flush=True)


def iso_week_label(dt: datetime | None = None) -> str:
    d = (dt or datetime.now(ZoneInfo("Asia/Taipei"))).date()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def week_range(dt: datetime | None = None) -> tuple[str, str]:
    """ISO week Mon..Sun for the week containing dt (Sun-of-week is end)."""
    d = (dt or datetime.now(ZoneInfo("Asia/Taipei"))).date()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def previous_week_label(current: str) -> str:
    """'2026-W19' → '2026-W18'. Handles year boundary via ISO calendar.

    Uses the Monday of `current` ISO week, subtracts 7 days, recomputes ISO
    label. Year-boundary safe (e.g. 2027-W01 → 2026-W52/W53)."""
    year_str, w_str = current.split("-W")
    year = int(year_str)
    week = int(w_str)
    # Monday of ISO week N of year Y. Python 3.8+: date.fromisocalendar.
    try:
        monday_curr = datetime.fromisocalendar(year, week, 1).date()
    except ValueError:
        # Fallback: today − 7d
        monday_curr = datetime.now(ZoneInfo("Asia/Taipei")).date() - timedelta(days=7)
    prev = monday_curr - timedelta(days=7)
    return f"{prev.isocalendar()[0]}-W{prev.isocalendar()[1]:02d}"


def week_range_for_label(label: str) -> tuple[str, str]:
    """ISO week label → (Mon, Sun) ISO date strings."""
    year_str, w_str = label.split("-W")
    monday = datetime.fromisocalendar(int(year_str), int(w_str), 1).date()
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


# --- Per-layer prompt budgets（serialized JSON 字元數）---
# 舊版是 json.dumps(bundle)[:80000] 整串硬切：實測 bundle 全長 ~173K，
# L3_crossref / L4_x_top 整層落在 80K 之外被砍光、L2 只剩前 27%（2026-07 bug）。
# 改為逐層配額 + 逐 item 裁切，確保四層都進得了 prompt。總和 ≈ 80K 不變。
LAYER_BUDGETS = {
    "L1_web": 30_000,      # 115 則淺摘要，round-robin 各來源前幾則已夠訊號發現
    "L2_pubmed": 20_000,   # 高價值層（7 位 OMI 作者近作含 abstract），給足讓每位作者首篇都進場
    "L3_crossref": 25_000,
    "L4_x_top": 5_000,
}


def _dump_len(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, indent=2))


def _count_items(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return sum(len(v) if isinstance(v, list) else 1 for v in data.values())
    return 1


def _truncate_layer(data, budget: int):
    """把單一 cache 層裁到 ≈budget 字元（serialized），以「整個 item」為單位丟棄
    （dict-of-lists 用 round-robin 輪流保留各 key 的 item，避免前面的 key 吃光配額），
    絕不從 JSON 字串中間硬切。已在配額內就原樣回傳。"""
    if _dump_len(data) <= budget:
        return data
    if isinstance(data, list):
        kept = []
        for item in data:
            kept.append(item)
            if _dump_len(kept) > budget:
                kept.pop()
                break
        return kept
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        kept = {k: ([] if isinstance(v, list) else v) for k, v in data.items()}
        progressed = True
        while progressed:
            progressed = False
            for k in list_keys:
                nxt = len(kept[k])
                if nxt >= len(data[k]):
                    continue
                kept[k].append(data[k][nxt])
                if _dump_len(kept) > budget:
                    kept[k].pop()
                    continue  # 這個 key 的下一筆塞不下；其他 key 或許還塞得下
                progressed = True
        return kept
    return data


def truncate_bundle_for_prompt(bundle: dict) -> dict:
    """逐層套 LAYER_BUDGETS，並 log 各層保留比例（除錯用）。"""
    out = {}
    for layer, data in bundle.items():
        budget = LAYER_BUDGETS.get(layer, 5_000)
        trimmed = _truncate_layer(data, budget)
        out[layer] = trimmed
        log(f"  prompt cache {layer}: {_count_items(trimmed)}/{_count_items(data)} items, "
            f"{_dump_len(trimmed)}/{_dump_len(data)} chars (budget {budget})")
    return out


def compute_scanned(bundle: dict) -> tuple[int, str]:
    """誠實整數 scanned = L1 篇 + L3 篇 + L2 篇（逐篇計數；L2 是各作者文章數
    加總，不是作者數）。從「截斷前」的完整 bundle 計算，由腳本注入 prompt——
    模型端不再推算（舊版要模型自己從被截斷的 cache 推算，實際不可能，導致
    W27 直接抄了 SOP 範例值 163 上線）。"""
    def n_items(layer: str) -> int:
        data = bundle.get(layer)
        if isinstance(data, dict):
            return sum(len(v) for v in data.values() if isinstance(v, list))
        if isinstance(data, list):
            return sum(1 for x in data if not (isinstance(x, dict) and "_error" in x))
        return 0
    n1 = n_items("L1_web")
    n2 = n_items("L2_pubmed")
    n3 = n_items("L3_crossref")
    return n1 + n3 + n2, f"L1={n1} + L3={n3} + L2={n2}"


def read_previous_index(prev_label: str) -> str:
    """Return previous week's index.md, head + tail truncated to ~12K chars.

    We keep BOTH head (front matter + 摘要 / OMI) and tail (Key Takeaways +
    引用 footnotes) so sub-agent can detect duplicate cases AND duplicate
    citations. Naive head-only truncation misses Key Takeaways which is the
    densest dedupe signal."""
    p = CONTENT_BASE / prev_label / "index.md"
    if not p.exists():
        return f"(上一期 {prev_label}/index.md 不存在)"
    text = p.read_text()
    if len(text) <= 12000:
        return text
    head = text[:8000]
    tail = text[-4000:]
    return f"{head}\n\n... [中段省略 {len(text) - 12000} chars] ...\n\n{tail}"



def build_prompt(week_label: str, prev_label: str, cache_bundle: dict, prev_index: str,
                 week_start: str, week_end: str) -> tuple[str, str]:
    """Returns (system, user_prompt)."""
    now_iso = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%FT%H:%M:%S%z")
    # Insert colon in tz offset (+0800 → +08:00)
    if len(now_iso) >= 5 and now_iso[-5] in "+-":
        now_iso = now_iso[:-2] + ":" + now_iso[-2:]

    # scanned 由腳本從完整 cache 實算（截斷前），模型只需原樣填入
    scanned_total, scanned_detail = compute_scanned(cache_bundle)

    system = f"""你是替 Bear（台灣急診科醫師）寫「急診心臟週報 {week_label}」的代筆。
**任務**：寫一份已排版完成、可直接上線的 markdown，**只回傳 markdown 內容本身**（不要 code fence、不要說明文字）。

## 排版規則（寫第一個字就遵守）

### Front matter（強制 · 新 schema）
```yaml
---
title: "<單一鉤子句，≤ 26 字；不要塞兩個 case + 冒號 + 斜線>"
subtitle: "<一句話副標 dek，italic；把本週最重要那句濃縮在這，取代舊摘要章節>"
shortTitle: "<列表用超短標，≤ 16 字>"
slug: "{week_label}"
week: "{week_label}"
weekRange: "{week_start} — {week_end}"
date: {now_iso}
coreTime: "3 分鐘"
fullTime: "12 分鐘"
readingTime: "12 分鐘"
scanned: {scanned_total}                # 腳本已實算（{scanned_detail}），原樣填入這個整數
picked: <挑成卡片的則數，整數 = Tier-2 卡數>
tags: ["OMI", "電生理", "Resus"]
practiceChanges:                # Tier 1，3–5 條祈使句，就是舊 Key Takeaways 升頂
  - text: "<祈使句：這週下一個班就能改的動作，可含 **粗體**>"
    source: "<出處，e.g. Smith ECG Blog 7-01>"
    href: "<對應 footnote 的原文連結>"
sections:                        # 卡數浮動：s1..sN，N = 本週真訊號數
  - {{ id: "changes", num: "▲", title: "本週改動" }}
  - {{ id: "s1",  num: "01", title: "<Tier2 卡1 短標>" }}
  - {{ id: "s2",  num: "02", title: "<Tier2 卡2 短標>" }}
  - {{ id: "s3",  num: "03", title: "<Tier2 卡3 短標>" }}
  - {{ id: "more", num: "▾", title: "延伸與出處" }}
---
```
**date 必須用上面那個值（{now_iso}）原樣填入**——不要寫死別的時間，否則 Hugo 會 skip 文章。
**scanned 必須用上面那個值（{scanned_total}）原樣填入**——腳本已從完整 cache 實算（{scanned_detail}），不要自己推算、不要抄任何範例值。
**Tier-1 只靠 front matter `practiceChanges` 驅動（single.html 自動渲染頂部卡），不要在正文再寫一次 Key Takeaways。**

### 三層訊號驅動結構（取代舊固定章節；H2 必加 anchor `{{#id}}`）

- **Tier 1 — 本週臨床改動**：不寫進正文，全靠 front matter `practiceChanges`（3–5 條祈使句）。id=changes，只出現一次（就是舊 Key Takeaways 升頂）。
- **Tier 2 — 本週重點卡片 ×N**（N＝本週真訊號數，浮動、不固定張數）：每張卡一個 `## <短標> {{#sN}}`（sN = s1/s2/s3…），內含四件事：
  1. **ECG 圖或標註式外連（二選一，缺這個就不寫這張卡）**：合法可嵌 → `{{{{< figure-ecg src alt caption source >}}}}`；版權不能轉載 → `{{{{< ecg-linkout href="...#:~:text=..." anno="看 <b>要看哪裡</b>" linktext="到原圖看波形 ↗" >}}}}`
  2. **三句話**：`**是什麼：**…` → `**為什麼要在意：**…`（放對比數字 + `{{{{< grade "回溯 · 單中心 · n=17 · 假說級" "retro" >}}}}` 證據分級 chip；⚠️ **grade 只吃位置參數，第二個參數直接寫 "rct"|"guide"|"retro"|"opinion"，絕對不可寫成 kind="retro"**——具名參數會讓 Hugo 在解析階段硬錯 Cannot mix named and positional parameters，**整站 build 失敗**，不只這一篇）→ `**所以呢：**…`（該做的動作）
  3. **footnote 出處** `[^id]`（Text-Fragment 跳原句）
  4. 台灣急診情境**併進相關卡末**，不獨立成章
- **Tier 3 — 延伸與出處**：`## 延伸與出處 {{#more}}`（single 頁預設收合）。放試驗數字細節、期刊速報（L3）、「誰這週有新作」壓成一段，最後接 footnote `## 引用` 區塊。

**硬規則**：
- 沒有 ECG 圖或標註式外連的 case **不寫**。
- **空章不存在**——不要寫「本週無新訊號」硬撐版面；沒訊號就少一張卡。
- 刪除獨立的「摘要 / 媒體動態 / 台灣急診備註 / Key Takeaways」四處重複；摘要濃縮成 subtitle 一句 dek。

**卡數軟目標（規則 A · 防太薄也防回頭填充）**：Tier-2 訊號卡目標 **3–5 張**。
- 真訊號 ≥3 則 → 有幾則寫幾張，**不封頂在 3**；強的獨立主題（如 AI-ECG／重要試驗）該給自己一張卡，不要硬折進別張卡的延伸。
- 真訊號 <3 則的**淡週** → **不可**用舊聞或補帶內容填充，改補**一張明確標示的「常青教學卡」**（board pearl／經典 case 重讀／一張值得回看的 ECG 圖／一個高頻陷阱複習），卡上標註「常青複習（非本週新訊號）」，讓淡週仍交付一個學習單位。
- **永遠禁止**：寫「本週無新訊號」硬撐、或把上週已寫過的東西換句話再寫一遍。

**配圖依卡型分兩類（規則 B · 修正上面「一律強制 ECG 圖／外連」）**：
- **case 卡**（討論一張特定 ECG）：**必附該 ECG**——能合法嵌 → `{{{{< figure-ecg >}}}}`；版權不能轉載 → `{{{{< ecg-linkout >}}}}` 標註「要看哪裡」＋跳原圖。**沒有可看的 ECG 就不寫這張 case 卡**。
- **研究／試驗／podcast／指引卡**（沒有單一 tracing）：用 `{{{{< ecg-linkout >}}}}` 當「來源預覽框」即可（anno 寫該則關鍵發現、linktext 連原始出處），**不強制單一 ECG 圖**。

### 段落分割
- 沒有任何一段超過 400 字
- 卡片內三句話（是什麼／為什麼要在意／所以呢）各自成段，不要黏成一大段
- 「對急診端的意義」「結果」「這意味著」「實務意義」「教學點是」「臨床上的 takeaway」前永遠是新段落起頭

### `<mark>` 螢光標記
- 每篇 ≤15 處
- 只標：數據對比 / 重磅結論 / 必記原則 / 數字 outcome
- 不標：一般敘述、文獻引用、章節標題、整段內容
- 跟粗體合併語法：`**<mark>關鍵詞</mark>**`

### H3 雙語（Tier-3 期刊速報 ＋ 卡片引用）
英文人名 / 期刊名後加繁中對照（Heart Rhythm = 心律期刊、JACC = 美國心臟學會期刊、Resuscitation = 急救期刊 等）

### 策展數字（不再寫文末附錄 4 卡片）
本週掃描/挑出數改用 front matter `scanned` / `picked` 兩個整數欄位表達（列表頁自動渲染成「本週掃了 N 則，挑出 M 則」）。`scanned` 已由腳本實算並填在上方模板（原樣照抄即可），你只需要數自己寫了幾張 Tier-2 卡填 `picked`。**不要**再產出 L1/L2/L3/L4 四張 source-card HTML 區塊，尤其**不要**產 L4 X.com 來源卡。

### Footnote 引用鐵律
- 多來源支撐同一主張 → 多 footnote `[^a][^b]`
- footnote 內容三件事：作者+出處+日期 / 原文那句（「」包起來）/ URL + Text Fragment（`#:~:text=...`）
- footnote 集中放在文章最末 `## 引用 {{#refs}}` 區塊
- footnote ID 用語意化 `[^smith-04-23]`，不用 `[^1]`

### L4 X.com — 只當後端訊號發現機制，不進讀者版面
給你的 L4_x_top 已先過濾 `RT @`。它只是**線索來源**：可以用來發現某條值得寫成 Tier-2 卡或 practiceChange 的訊號，但**不要**在正文寫「追蹤作者 X.com 端」段落、**不要**產 X.com 來源卡。真的採用某則推文的觀點時，一樣要回到原始 blog / paper 補 footnote，不要拿推文本身當唯一出處。剔除非 ECG 主題（政治、社交、生日問候）的判準保留 = 含 ECG/EKG/STEMI/OMI/NSTEMI/Wellens/Sgarbossa/arrhythmia/AFib/VT/SVT/syncope/cardiac arrest/Brugada/WPW/Mobitz/AI ECG/PMcardio/Queen of Hearts/case/teaching/rhythm/ablation/pacemaker/ICD 等關鍵字。

### 風格
- **臺灣繁體中文，禁簡體 / 大陸用語**（網絡→網路、視頻→影片、信息→資訊、信號→訊號、實時→即時、心律失常→心律不整 等）
- 醫學雜誌 editorial 語氣；每張 Tier-2 卡走「是什麼 → 為什麼要在意 → 所以呢」三句結構
- 字數訊號驅動、該短就短（不必湊 3000+）

### 不要做
- ❌ 不要寫鬆散版（這 skill 的核心就是排版在寫稿時就生效）
- ❌ 不要重覆上一期已寫過的 case / trial（見下面防重覆 brief）
- ❌ 不要回傳 markdown code fence 包整篇（直接吐 frontmatter 開頭的純 markdown）
- ❌ 不要寫沒有 ECG 圖或標註式外連的 case
- ❌ 不要寫空章（「本週無新訊號」硬撐版面）——沒訊號就少一張卡
- ❌ 不要獨立寫「摘要 / 媒體動態 / 台灣急診備註 / Key Takeaways」四章（已被 Tier-1 + subtitle + 卡片內台灣情境取代）
- ❌ 不要在讀者版面出現 X.com（不寫追蹤作者 X.com 段、不出 X.com 來源卡）
"""

    # 逐層配額截斷（取代舊 json.dumps(bundle)[:80000] 整串硬切——那會把
    # L3/L4 整層砍光、L2 砍半）。90K 只是防呆安全網，正常永遠不會觸發。
    safe_bundle = truncate_bundle_for_prompt(cache_bundle)
    cache_json = json.dumps(safe_bundle, ensure_ascii=False, indent=2)
    if len(cache_json) > 90_000:
        log(f"WARN: cache_json {len(cache_json)} chars exceeds 90K safety cap, hard-cutting tail")
        cache_json = cache_json[:90_000]

    user = f"""## 本期：{week_label}（{week_start} — {week_end}）

## 上一期已涵蓋（{prev_label}，自己讀內文確認後不要重覆）

```markdown
{prev_index}
```

## 4 層 cache（JSON / 已過濾 RT 的 L4 top 50；各層已依配額裁切）

```json
{cache_json}
```

請開始寫，回傳完整 markdown（從 `---` frontmatter 開頭）。
"""
    return system, user


def load_cache_for_prompt() -> dict:
    bundle: dict = {}
    for layer, p in CACHE_FILES.items():
        try:
            bundle[layer] = json.loads(p.read_text())
        except Exception as e:
            bundle[layer] = {"_error": str(e)}
    return bundle


def main() -> int:
    global CONTENT_BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-repo", required=True)
    ap.add_argument("--week", default=None, help="預設＝台北時間今天所在 ISO 週")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    CONTENT_BASE = Path(args.blog_repo).resolve() / "content/er-cardio-weekly"
    week_label = args.week or iso_week_label()
    prev_label = previous_week_label(week_label)
    week_start, week_end = week_range_for_label(week_label)

    bundle = load_cache_for_prompt()
    errors = [k for k, v in bundle.items() if isinstance(v, dict) and "_error" in v]
    if len(errors) == len(bundle):
        log(f"所有 cache 都讀不到：{errors}")
        return 2
    system, user = build_prompt(week_label, prev_label, bundle,
                                read_previous_index(prev_label), week_start, week_end)
    user += ("\n\n（雲端版註：本期沒有 L4 X.com 資料，忽略規則裡提到 L4_x_top 的部分。"
             f"讀不到的層：{errors or '無'}）\n")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# SYSTEM\n\n{system}\n\n# USER\n\n{user}", encoding="utf-8")
    meta = {"week": week_label, "prev": prev_label, "range": [week_start, week_end],
            "missing_layers": errors}
    (out.parent / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    log(f"brief → {out} ({out.stat().st_size} bytes); meta={meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
