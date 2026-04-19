# CLAUDE.md — ECG Weekly Report

## Project Purpose

Auto-generate weekly Markdown reports on ECG / emergency cardiology trends from:
- Web scrapers (LITFL / Dr Smith ECG Blog / EMCrit / REBEL EM / First10EM / ALiEM / Core EM / ACC / ESC / HRS / AHA)
- ECG Weekly (Amal Mattu) public previews — title + date + HPI case summary
- CrossRef API — Heart Rhythm / JACC-EP / Circulation-AE / J Electrocardiology / Annals EM / Resuscitation
- (Future) ECG Weekly deep-dive: login → video download → /transcribe → full .md
- (Optional) PubMed MCP / ClinicalTrials.gov MCP / OpenEvidence MCP

---

## Before Writing a New Report

**MANDATORY — do this BEFORE writing a single word of content:**

```bash
# 1. Find the latest report
PREV=$(ls reports/ -t | head -1)
echo "Previous report: $PREV"

# 2. Read it fully — note every case, trial, guideline, and topic covered
# 3. Grep key topic names to see what's already documented
grep -E "Wellens|Sgarbossa|De Winter|OMI|Brugada|BRASH|Queen of Hearts|PFA|GLP-1" reports/$PREV
```

After reading the previous report, answer these before writing:
- Which Dr Smith cases were already featured? → **skip or cite only if significantly updated**
- Which ECG Weekly workouts were already covered? → **skip unless referenced in a new discussion**
- Which guidelines / trials had data last week? → include only if new follow-up or approval

**Do NOT repeat** any case with identical clinical details. Mark new follow-up data explicitly: `[更新]` before the subsection heading.

If a section has no genuinely new data this week: write `_本週無新訊號_` and move on.

---

## Report File Naming

```
reports/YYYY-WNN.md
```

Use ISO week number: `python3 -c "from datetime import date; d=date.today(); print(f'{d.year}-W{d.isocalendar()[1]:02d}')"`.

---

## Report Structure

### Required Sections (繁體中文)

```
# ECG / 急診心臟學週報 — YYYY-WNN

> 生成日期：YYYY-MM-DD｜資料來源：...
> 涵蓋期間：YYYY-MM-DD 至 YYYY-MM-DD

---

## 摘要
（本週五大訊號 — bullet points，具體病例 / 具體數據 / 具體推論）

## 一、OMI / STEMI 判讀（Dr Smith、ECG Weekly、Queen of Hearts）
## 二、Arrhythmia 心律不整新知（AF / SVT / VT / 電風暴）
## 三、Conduction 傳導異常與 Channelopathy（AV block、LBBB、Brugada、LQTS）
## 四、Pacemaker / ICD / CRT 與 Ablation
## 五、AI ECG 與穿戴裝置
## 六、Cardiac Arrest / Resuscitation
## 七、BRASH / 急診 ECG 毒物相關（hyperK、digoxin、TCA）
## 八、教學案例精選（LITFL、ECG Weekly、Dr Smith Blog）

## 九、蜥蜴LLM 點評
（practice-changing vs hypothesis-generating vs context-dependent）

## 十、媒體動態
（各來源新聞表 — 標題 / 日期 / 關鍵詞）

## 十一、文獻速報 — CrossRef 期刊
（ECG-filtered 論文列表）

## 十二、台灣急診情境備註
（若有和台灣 ED 實務相關的重點）

## 十三、本週 Key Takeaways
```

Sections without new data this week should say: `_本週無新訊號_`

---

## Writing Style

- Language: **臺灣繁體中文**，英文術語保留原文（ECG、STEMI、OMI、NSTEMI、Sgarbossa、Wellens、De Winter、BRASH、LVH 等）
- 不使用簡體字與大陸用語（sub-agent 翻譯後必跑 OpenCC s2tw 保險）
- Every clinical claim must cite source (trial name、Dr Smith 文章標題、ECG Weekly workout 名稱 + 連結)
- Tables: use Markdown tables for comparative data
- Numbers: always include HR / CI / PFS / OS / ORR when available
- 避免空泛 superlatives；每個「顯著」都要帶數字

---

## Data Pipeline

Run in order before writing:

```bash
uv run python main.py scrape          # 11 web sources (LITFL / Dr Smith / EMCrit / REBEL EM / ECG Weekly / ACC / ESC / HRS / AHA ...)
uv run python main.py journals        # CrossRef (Heart Rhythm / JACC-EP / Circulation-AE / J ECG / Annals EM / Resuscitation)
```

For full pipeline (including Twitter if credentials available):

```bash
uv run python main.py run
```

Cached data locations:
- `data/webscrape_cache.json` — web articles + ECG Weekly HPI previews
- `data/journals_cache.json` — CrossRef journal articles (pre-screened, not yet final-filtered)

**CrossRef filtering note:** The Python fetcher applies a keyword pre-screen only (broad net).
When writing the report, read `data/journals_cache.json` and **filter in-session** — discard any
article whose primary topic is not ECG / emergency cardiology (e.g. structural heart trials that
share "ventricular" or "ischemia" terms). Only include articles confirmed ECG-relevant in the
`## 文獻速報` section.

---

## ECG Weekly (Amal Mattu) — 兩層抓取

### Layer 1 — 公開 preview（已整合進 `uv run python main.py scrape`）
每篇 workout 頁面的 preview 文字不需登入即可抓，包含：
- 真實標題
- 發布日期
- HPI 病例摘要（約 200-500 字）

直接寫入 `data/webscrape_cache.json` 的 `ECG Weekly (Amal Mattu)` 區段。

### Layer 2 — 登入版 deep-dive（待建）
完整影片 + Amal 講解文字需要 membership 登入。計畫：
1. Playwright + macOS Keychain 存憑證
2. 下載影片 (yt-dlp 處理 Vimeo / Wistia embed)
3. 呼叫 `/transcribe` skill 產逐字稿
4. 合併：標題 + 日期 + 作者文字 + 逐字稿 → 單篇 `reports/ecgweekly/YYYY-MM-DD-SLUG.md`
5. 週報只摘要+連結，不貼全文（避版權問題）

此層獨立於週報；週報生成時只讀 Layer 1 預覽即可。

---

## 蜥蜴LLM 點評 Section

Use `mcp__openevidence__oe_ask` with a prompt like:

```
Based on the following ECG / emergency cardiology findings from this week, classify each as:
- Practice-changing (changes standard of care NOW)
- Hypothesis-generating (promising but needs confirmation)
- Context-dependent (changes practice for specific subgroup only)

[list findings with case/trial names and key numbers]
```

Extract result with: `result.extracted_answer_raw`

---

## After Writing

1. Check word count: report should be 3000–8000 words
2. Verify every table has header separators (`|---|---|`)
3. Commit: `git add reports/YYYY-WNN.md && git commit -m "report: YYYY-WNN"`
4. Push → GitHub Action auto-publishes to Wiki

---

## Duplicate-Avoidance Checklist

Before finalising, cross-check against the previous report:

```bash
PREV=$(ls reports/ -t | head -2 | tail -1)
# ECG case / trial / guideline names
grep -E "Wellens|Sgarbossa|De Winter|OMI|Brugada|BRASH|Queen of Hearts|PFA|GLP-1|UMEM Cases" reports/$PREV
# Dr Smith case signatures
grep -E "[0-9]+ (yo|year-old)" reports/$PREV | head -20
```

Rules:
- Same case + same clinical details → **delete the section**
- Same trial + new data → keep with `[更新]` tag
- Brand new case / finding → include normally

---

## Switching to Another Topic

This project's original design is **topic-agnostic** — all domain knowledge lives in
`source/*.yml` and `config/seeds.txt`. To switch away from ECG (e.g. back to breast cancer
or to DLBCL), modify the 6 YAML files + seeds.txt per the README. No Python changes needed.

If the new topic needs a custom scraper (like `_fetch_ecgweekly`), add a new `type:` in
`web_sources.yml` and a corresponding function in `src/webscraper.py`.
