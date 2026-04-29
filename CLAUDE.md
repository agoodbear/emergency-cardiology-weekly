# CLAUDE.md — 急診心臟週報 (ER Cardio Weekly) 寫稿 SOP

> 寫稿時這份 SOP 是 single source of truth。**排版規則在寫稿時就要生效，不是事後補。**
> 全自動產出走 `/ercw-format` skill。

## 專案目的

每週把 4 層來源訊號整理成一篇上線版 markdown，直接寫到 Hugo 站 `agoodbear.github.io/content/er-cardio-weekly/YYYY-WNN/index.md`，push 後 GitHub Actions 自動部署到 `https://agoodbear.github.io/er-cardio-weekly/YYYY-WNN/`。

---

## 4 層來源（每週日 03:00 自動跑 / 手動觸發）

| 層 | 來源 | 命令 | Cache |
|---|---|---|---|
| L1 | Web 11 來源（Dr Smith / ECG Weekly / LITFL / EMCrit / REBEL EM / First10EM / ALiEM / Core EM / ACC / ESC / HRS / AHA） | `main.py scrape` | `data/webscrape_cache.json` |
| L2 | PubMed 7 位作者（Smith / Meyers / Grauer / McLaren / Aslanger / Frick / Ghali）| `main.py authors` | `data/authors_cache.json` |
| L3 | CrossRef 10 本期刊（Heart Rhythm / JACC-EP / Circ-AE / J Electrocard / Annals EM / Resus / Europace / JACC / EHJ / JAMA Cardiology）| `main.py journals` | `data/journals_cache.json` |
| L4 | X.com 8 位指定 handle（@smithECGBlog / @PendellM / @ekgpress / @AslangerE / @ecgcases / @EM_RESUS / @willyhfrick / @RobertHermanMD）| `main.py fetch`（需先 `main.py setup` 提供 cookie）| SQLite `db.sqlite` |

全跑：`uv run python main.py run`（fetch + discover + scrape + journals + authors + report 全鏈）

---

## 寫稿前 MANDATORY checklist

```bash
# 1. 找上一期已上線版本
PREV_HUGO=~/Documents/GitHub/agoodbear.github.io/content/er-cardio-weekly
ls -t $PREV_HUGO | head -1

# 2. 完整讀上一期 — 列出所有已涵蓋的 case / trial / 期刊
# 3. grep 重點主題防重覆
PREV_FILE=$(ls -t $PREV_HUGO/*/index.md | head -1)
grep -E "Wellens|Sgarbossa|De Winter|OMI|Brugada|BRASH|Queen of Hearts|PFA|GLP-1|UMEM Cases|CAAN-AF|STOPSTORM" $PREV_FILE
```

回答以下才開始寫：
- 哪些 Dr Smith case 已寫過？→ **跳過或只有顯著更新才寫**
- 哪些 ECG Weekly workout 已寫過？→ **跳過除非新討論引用**
- 哪些 trial / guideline 上週已給數據？→ **只在新追蹤資料才寫**

**DO NOT REPEAT** 同 case 同臨床細節。新追蹤資料用 `[更新]` 標在小標前。

某章節這週確實沒新訊號 → 寫 `_本週無新訊號_` 帶過。

---

## 輸出位置（直接寫到 Hugo content）

```
~/Documents/GitHub/agoodbear.github.io/content/er-cardio-weekly/YYYY-WNN/index.md
```

⚠️ **不要寫到 `reports/YYYY-WNN.md`**——那是 Phase 1 GitHub Wiki 棄用 path。Wiki workflow 在 fork repo 沒初始化會 fail，已棄用，**忽略**。

ISO 週次：
```bash
python3 -c "from datetime import date; d=date.today(); print(f'{d.year}-W{d.isocalendar()[1]:02d}')"
```

---

## Front matter（強制欄位）

```yaml
---
title: "<本週主題標題>"
subtitle: "<副標一句話 italic>"
slug: "YYYY-WNN"                   # 必填，避免中文 title 變 URL 編碼
week: "YYYY-WNN"
weekRange: "YYYY-MM-DD — YYYY-MM-DD"
date: YYYY-MM-DDT20:00:00+08:00    # 固定 20:00（防 Hugo future-date skip）
readingTime: "21 分鐘"
tags: ["OMI", "AI ECG", "裝置", "Arrhythmia", "Resus"]
sections:
  - { id: "tldr", num: "0",    title: "摘要" }
  - { id: "omi",  num: "I",    title: "OMI / 急性冠症" }
  - { id: "arr",  num: "II",   title: "Arrhythmia / 節律" }
  - { id: "con",  num: "III",  title: "Conduction / 傳導" }
  - { id: "dev",  num: "IV",   title: "裝置" }
  - { id: "ai",   num: "V",    title: "AI ECG / 穿戴" }
  - { id: "res",  num: "VI",   title: "Resus / 急救" }
  - { id: "tox",  num: "VII",  title: "BRASH / 毒物" }
  - { id: "tch",  num: "VIII", title: "教學案例" }
  - { id: "aut",  num: "IX",   title: "追蹤作者本週新作" }
  - { id: "med",  num: "X",    title: "媒體動態" }
  - { id: "ref",  num: "XI",   title: "文獻速報" }
  - { id: "tw",   num: "XII",  title: "台灣急診備註" }
  - { id: "key",  num: "XIII", title: "Key Takeaways" }
---
```

不要重覆寫 H1（`# ECG / 急診心臟學週報 — YYYY-WNN`）—— Hugo template 會從 `title` 渲染標題。

---

## 13 章節結構（H2 必加 anchor `{#id}`）

```markdown
## 摘要 / 本週速讀 {#tldr}
（**本週 5 大訊號** — 導言 + 第一/二/三 共 4 段 + bullet 清單，每個 bullet 一條訊號）

## 一、OMI / STEMI 判讀 {#omi}
## 二、Arrhythmia 心律不整新知 {#arr}
## 三、Conduction 傳導異常與 Channelopathy {#con}
## 四、Pacemaker / ICD / CRT 與 Ablation {#dev}
## 五、AI ECG 與穿戴裝置 {#ai}
## 六、Cardiac Arrest / Resuscitation {#res}
## 七、BRASH / 急診 ECG 毒物相關 {#tox}
## 八、教學案例精選 {#tch}
## 九、追蹤作者本週新作（PubMed）{#aut}      # L2 章節，本期 7 位作者整理
## 十、媒體動態 {#med}                       # L1 章節
## 十一、文獻速報 — CrossRef 期刊 {#ref}     # L3 章節
## 十二、台灣急診情境備註 {#tw}
## 十三、本週 Key Takeaways {#key}
```

每章「導言 → 3-4 重點 → **Bottom line**」醫學 editorial 結構。
某章沒新訊號 → 寫 `_本週無新訊號_`。

---

## 排版規則（**寫稿時就要遵守，不是事後補**）

### 1. 長段落分割

**沒有任何一段超過 400 字。** 寫到一半感覺長了 → 立刻換段。

**永遠是新段落起頭**的轉折詞（在「。」後遇到時換段）：
- 對急診端的意義是 / 對台灣急診的意義是
- 對 ED / 對 EP / 對 ICU
- 這意味著什麼？/ 這意味著
- 結果： / 實務意義是 / 實務意義
- 教學點是 / Amal 的教學點是 / Magnus 的
- 重點數據已展開
- Subgroup 點：
- 臨床上的 takeaway：

**摘要章節結構強制**：
```
W?? 的訊號集中在三條主軸。

**第一，<主題一>。** <展開段>。

**第二，<主題二>。** <展開段>。

**第三，<主題三>。** <展開段>。

本週五則值得在晨會帶過的：

- 訊號 1（出處）
- 訊號 2（出處）
- 訊號 3（出處）
- 訊號 4（出處）
- 訊號 5（出處）
```

### 2. `<mark>` 螢光標記重點

每篇 ≤15 處 mark，**只標**：
- 數據對比（"94.1% vs 47.1%" / "yield 不輸 patch monitor"）
- 重磅結論（"在隨機試驗下站不住腳" / "把漏判率降到接近零"）
- 必記原則（"sodium channel toxicity 用 lidocaine + magnesium，不要 amiodarone"）
- 數字 outcome（"中位數降低 80%" / "存活 77%"）

格式：
- 純標：`<mark>關鍵詞</mark>`
- 跟既有粗體合併：`**<mark>關鍵詞</mark>**`

**不標**：一般敘述、文獻引用 / DOI / PMID、章節標題、整段 paragraph 級別。

### 3. H3 雙語

章節 IX-XI 中作者 / 期刊 / 來源名英文後加繁中對照：

| 英文 | 繁中 |
|---|---|
| Heart Rhythm | 心律期刊 |
| J Electrocardiology | 心電圖期刊 |
| Resuscitation | 急救期刊 |
| European Heart Journal / EHJ | 歐洲心臟期刊 |
| Circulation: Arrhythmia and Electrophysiology | 循環—心律電生理 |
| JACC | 美國心臟學會期刊 |
| JACC-EP | JACC 電生理 |
| JAMA Cardiology | JAMA 心臟 |
| Annals EM | 急診醫學年鑑 |
| Europace | 歐洲節律 |
| LITFL | 澳洲急診維基 |
| EMCrit | 重症急診 |
| REBEL EM | REBEL 急診部落格 |
| First10EM | 第一個 10 分鐘 |
| Core EM | Core 急診 |
| ACC / ESC / AHA / HRS | 美國心臟學會 / 歐洲心臟學會 / 美國心臟協會 / 美國心律學會 |
| ECG Weekly (Mattu) | Mattu 心電圖週刊 |
| Stephen W. Smith | Hennepin Healthcare, OMI 主軸 |
| Pendell Meyers | OMI 概念共同創立者 |
| Ken Grauer | KG-EKG Press, 佛州 ECG 教學 |
| Jesse McLaren | 多倫多 ECG Cases blog 主理人 |
| Emre Aslanger | 伊斯坦堡 OMI 共同作者 |
| Willy Frick | WashU 心臟科 |
| Sam Ghali | EM Resus 教學者 |

### 4. 文末附錄 4 卡片

**每篇結尾必加。** 從 cache 讀統計：

```python
import json
w = json.load(open('data/webscrape_cache.json'))   # L1
a = json.load(open('data/authors_cache.json'))     # L2
j = json.load(open('data/journals_cache.json'))    # L3
L1_total = sum(len(arts) for arts in w.values())
L3_total = sum(len(arts) for arts in j.values())
```

附在「下週預計追蹤」之後：

```html
<section class="sources-appendix" id="sources">
<div class="sources-title">附錄 · 本週原始訊號清單</div>
<p class="sources-intro">本週報底下 4 層來源獨立彙整。點「看完整 →」進該層 archive 看時間流。</p>
<div class="sources-grid">
<div class="source-card">
<div class="source-label">L1 · 部落格 / 學會</div>
<div class="source-count">{L1_total}<span class="unit">篇本週新文</span></div>
<ul>
<li><span class="li-en">{Source} <strong>{N}</strong></span><span class="li-zh">{中文翻譯}</span></li>
<!-- top 5 by count -->
</ul>
<a class="source-more" href="/er-cardio-weekly/sources/blog/">看完整 →</a>
</div>
<!-- L2 / L3 / L4 同樣四張卡 -->
</div>
</section>
```

⚠️ HTML 內容**所有行頂左對齊，不能縮排**（goldmark 4 空格觸發 code-block）。

---

## 寫作風格

- **臺灣繁體中文**，禁簡體 / 大陸用語（OpenCC s2tw 保險）
- 醫學雜誌 editorial 風：每章「導言 → 重點 → Bottom line」
- 英文術語保留（ECG、STEMI、OMI、NSTEMI、Sgarbossa、Wellens、De Winter、BRASH、LVH 等）
- 每個臨床主張**必附出處**：trial 名 / 文章標題 + 連結 / DOI / PMID
- 表格用 markdown，正確的 `|---|---|` 分隔線
- 數字必含：HR / CI / PFS / OS / ORR / sensitivity / specificity / AUCROC
- 字數 3000-8000

---

## 蜥蜴 LLM 點評（Section 九 替代或補充）

`mcp__openevidence__oe_ask` 可選。若沒跑 OE，章節 IX 用 PubMed 追蹤作者本週新作 取代 LLM 點評（W17 即此模式）。

---

## After Writing

寫完不直接 commit/push。回報：
- 字數
- 拆段數 / mark 數 / 表格數
- 本週主軸 3 句話
- cache 看不懂的怪資料

主對話會：
1. 提供本機 hugo server 預覽 URL
2. 等使用者確認
3. 才 commit + push

push 流程（主對話統一做）：
```bash
cd ~/Documents/GitHub/agoodbear.github.io
git fetch origin
git status -sb        # 確認 hugo-source branch、與 origin 同步
git add content/er-cardio-weekly/YYYY-WNN/
git commit -m "post: er-cardio-weekly YYYY-WNN"
git push origin hugo-source
gh run list -R agoodbear/agoodbear.github.io --branch hugo-source --limit 1
```

確認 GitHub Actions conclusion=success 才算上線到 `https://agoodbear.github.io/er-cardio-weekly/YYYY-WNN/`。

---

## Duplicate-Avoidance Checklist

寫完前再 grep 防重覆：

```bash
PREV_FILE=$(ls -t ~/Documents/GitHub/agoodbear.github.io/content/er-cardio-weekly/*/index.md | head -2 | tail -1)
grep -E "Wellens|Sgarbossa|De Winter|OMI|Brugada|BRASH|Queen of Hearts|PFA|GLP-1|UMEM Cases|CAAN-AF|STOPSTORM" $PREV_FILE
grep -E "[0-9]+ (yo|year-old)" $PREV_FILE | head -20
```

規則：
- 同 case 同臨床細節 → **整段刪**
- 同 trial 新數據 → 標 `[更新]` 保留
- 全新內容 → 正常寫

---

## ECG Weekly (Amal Mattu) — 兩層抓取

### Layer 1（已整合進 `main.py scrape`）
公開 preview 不需登入：標題 + 日期 + HPI 摘要（200-500 字）。直接寫進 `data/webscrape_cache.json` 的 `ECG Weekly (Amal Mattu)` 區段。

### Layer 2（待建）
完整影片 + Amal 講解需 membership 登入：
1. Playwright + macOS Keychain 存憑證
2. yt-dlp 下載（Vimeo / Wistia embed）
3. 呼叫 `/transcribe` skill 產逐字稿
4. 合併 → `reports/ecgweekly/YYYY-MM-DD-SLUG.md`（單獨歸檔，不放週報）
5. 週報只摘要 + 連結，避版權問題

---

## 已知 gotchas

1. **Hugo future-date skip**：article date 寫 `T20:00:00+08:00`（未來時間），本機預覽要 `--buildFuture`
2. **中文 title 變 URL 編碼**：必須 `slug: "YYYY-WNN"`
3. **HTML 縮排觸發 goldmark code-block**：附錄區塊 `<div>` 全部頂左
4. **GitHub Pages CDN cache**：push 後 1-3 分鐘上線；驗證 URL 加 `?v=$(date +%s)` 破 cache
5. **L4 cookie 過期**：30-90 天要重 setup `uv run python main.py setup`
6. **CrossRef pre-screen 太寬**：寫稿時讀 `data/journals_cache.json` 要再 in-session filter，丟掉非 ECG 主題（如 structural heart trials 共享 "ventricular" / "ischemia" 字眼者）

---

## 切換主題

本專案 topic-agnostic 架構。要從 ECG 切到別主題只改：
- `source/keywords.yml` / `drug_groups.yml` / `web_sources.yml` / `journals.yml` / `search_queries.yml` / `twitter.yml` / `authors.yml`
- `config/seeds.txt`

不需改 Python。新主題若要新爬蟲（如 `_fetch_ecgweekly`），加 `web_sources.yml` 的 type + `src/webscraper.py` 對應 function。

---

## 相關檔案

- `~/.claude/skills/ercw-format/SKILL.md` — 全自動產出 skill（觸發詞「寫 W?? 週報」）
- 主對話 memory `project_ecg_weekly.md` — Phase 規劃
- 主對話 memory `reference_hugo_blog.md` — Hugo 部署規則
- 主對話 memory `project_hugo_blog_maintenance.md` — repo 維修分工
- `~/Documents/GitHub/agoodbear.github.io/content/er-cardio-weekly/2026-W17/index.md` — 第一篇上線版本，可參考結構
