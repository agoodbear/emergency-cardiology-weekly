# CLAUDE.md — 急診心臟週報 (ER Cardio Weekly) 寫稿 SOP

> 寫稿時這份 SOP 是 single source of truth。**排版規則在寫稿時就要生效，不是事後補。**
> 全自動產出走 `/ercw-format` skill。

## 專案目的

每週把 4 層來源訊號整理成一篇上線版 markdown，直接寫到 Hugo 站 `agoodbear.github.io/content/er-cardio-weekly/YYYY-WNN/index.md`，push 後 GitHub Actions 自動部署到 `https://agoodbear.github.io/er-cardio-weekly/YYYY-WNN/`。

---

## 4 層來源（launchd：週日 02:00 抓料 / 週日 10:00 寫稿並自動 push；亦可手動觸發）

| 層 | 來源 | 命令 | Cache |
|---|---|---|---|
| L1 | Web 11 來源（Dr Smith / ECG Weekly / LITFL / EMCrit / REBEL EM / First10EM / ALiEM / Core EM / ACC / ESC / HRS / AHA） | `main.py scrape` | `data/webscrape_cache.json` |
| L2 | PubMed 7 位作者（Smith / Meyers / Grauer / McLaren / Aslanger / Frick / Ghali）| `main.py authors` | `data/authors_cache.json` |
| L3 | CrossRef 10 本期刊（Heart Rhythm / JACC-EP / Circ-AE / J Electrocard / Annals EM / Resus / Europace / JACC / EHJ / JAMA Cardiology）| `main.py journals` | `data/journals_cache.json` |
| L4 | X.com 8 位指定 handle（@smithECGBlog / @PendellM / @ekgpress / @AslangerE / @ecgcases / @EM_RESUS / @willyhfrick / @RobertHermanMD）| `main.py fetch`（2026-04-30 起改走 Playwright，新 fetcher 在 `src/fetcher_playwright.py`；twscrape 對最新 X 反爬完全失效已棄用）| SQLite `data/tweets.db` |

**L4 寫稿前必做二次 filter**（fetcher 抓的是該作者所有推文，不是 ECG 推文）：
1. 跳過 `content` 以 `RT @` 開頭（轉推他人，且作者常轉政治推文夾雜）
2. 跳過非 ECG 主題（政治 / 榮譽 / 早安 / 生日 / 求職）
3. 保留：作者本人發 + 含 ECG/STEMI/OMI/Wellens/De Winter/arrhythmia/AFib/VT/SVT/syncope/cardiac arrest/Brugada/Mobitz/AI ECG/PMcardio/case/teaching/ablation/pacemaker/ICD 等關鍵字
4. 過濾後某作者剩 0 條 → 章節寫 `_本週無 ECG 主題新作_`，**不要硬湊政治推文當醫學內容**

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

硬規則：某主題這週沒訊號 → **不寫這張卡**（空章不存在，不要寫「本週無新訊號」硬撐版面）。

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

## Front matter（強制欄位 · 三層訊號驅動新 schema）

```yaml
---
title: "<單一鉤子句，≤ 26 字；不要塞兩個 case + 冒號 + 斜線>"
subtitle: "<一句話副標 dek，italic；把本週最重要那句濃縮在這，取代舊摘要章節>"
shortTitle: "<列表用超短標，≤ 16 字；list.html 優先用，缺則 fallback title>"
slug: "YYYY-WNN"                   # 必填，避免中文 title 變 URL 編碼
week: "YYYY-WNN"
weekRange: "YYYY-MM-DD — YYYY-MM-DD"
date: YYYY-MM-DDTHH:MM:SS+08:00    # ⚠️ 用寫稿當下時間（date '+%FT%H:%M:%S%z'），禁寫死固定時間
coreTime: "3 分鐘"                 # 取代 readingTime 當主秀
fullTime: "12 分鐘"
readingTime: "12 分鐘"             # 保留當 fallback（舊模板相容）
scanned: 163                       # 本週掃描來源總則數（整數，L1+L3+L2 推算）
picked: 3                          # 挑成卡片的則數（整數 = Tier-2 卡數）
tags: ["OMI", "電生理", "Resus"]
practiceChanges:                   # Tier 1，3–5 條祈使句（= 舊 Key Takeaways 升頂）
  - text: "<祈使句，可含 **粗體**>"
    source: "<出處，e.g. Smith ECG Blog 7-01>"
    href: "<對應 footnote 原文連結>"
sections:                          # 卡數浮動：s1..sN，N = 本週真訊號數
  - { id: "changes", num: "▲", title: "本週改動" }
  - { id: "s1",  num: "01", title: "<Tier2 卡1 短標>" }
  - { id: "s2",  num: "02", title: "<Tier2 卡2 短標>" }
  - { id: "s3",  num: "03", title: "<Tier2 卡3 短標>" }
  - { id: "more", num: "▾", title: "延伸與出處" }
---
```

- `sections` 每個 `id` 必對應內文 H2 anchor `{#id}`（scroll-spy 靠這個）。Tier-2 每卡一個 `## <標題> {#sN}`；Tier-3 是 `## 延伸與出處 {#more}`。
- Tier-1 只靠 `practiceChanges` 驅動（single.html 自動渲染頂部卡），**不要**在正文再寫一次 Key Takeaways。

不要重覆寫 H1（`# ECG / 急診心臟學週報 — YYYY-WNN`）—— Hugo template 會從 `title` 渲染標題。

---

## 三層訊號驅動結構（H2 必加 anchor `{#id}`；取代舊固定 10 章）

- **Tier 1 — 本週臨床改動**（id=changes）：3–5 條祈使句，釘在文章最上方，只出現一次。**不寫進正文**，由 front matter `practiceChanges` 陣列驅動（single.html 自動渲染）。就是舊 Key Takeaways 升頂。
- **Tier 2 — 本週重點卡片 ×N**（N＝本週真訊號數，浮動、不固定章數）：每則一個 `## <短標> {#sN}`，內含：
  1. **ECG 圖或標註式外連（二選一，缺這個就不寫這張卡）**：合法可嵌 → `{{< figure-ecg src alt caption source >}}`；版權不能轉載 → `{{< ecg-linkout href="...#:~:text=..." anno="看 <b>要看哪裡</b>" linktext="到原圖看波形 ↗" >}}`
  2. **三句話**：`**是什麼：**…`／`**為什麼要在意：**…`（放對比數字 + `{{< grade "回溯 · 單中心 · n=17 · 假說級" "retro" >}}` 證據分級 chip，第二個參數 = rct|guide|retro|opinion）／`**所以呢：**…`（該做的動作）
     - ⚠️ **grade 只吃位置參數，不可寫 `kind="retro"`**。`layouts/shortcodes/grade.html` 用的是 `.Get 0` / `.Get 1`；寫成具名參數 Hugo 會在**解析階段**就硬錯 `Cannot mix named and positional parameters`，**整站 build 失敗**（不只這篇）。2026-08-02 W30 起這行 SOP 範例本身寫錯，導致 W30–W33 共 18 處壞語法，整個部落格兩週沒能部署（連 ai-learning 等其他文章一起被擋），2026-08-16 才發現並修掉。
  3. **footnote 出處**（Text-Fragment 跳原句）
  4. 台灣急診情境**併進相關卡末**，不獨立成章
- **Tier 3 — 延伸與出處**（id=more，single 頁預設收合）：`## 延伸與出處 {#more}`。放試驗數字細節、期刊速報（L3）、「誰這週有新作」壓成一段，最後接 footnote `## 引用` 區塊。

**硬規則**：
- 沒有 ECG 圖或標註式外連的 case **不寫**。
- **空章不存在**——不要寫「本週無新訊號」硬撐版面；沒訊號就少一張卡。
- 刪除獨立的「摘要 / 媒體動態 / 台灣急診備註 / Key Takeaways」四處重複來源；摘要濃縮成 subtitle 一句 dek，台灣情境併進相關卡片。
- **L4 X.com 不進讀者版面**：不寫「追蹤作者 X.com 端」段落、不出 X.com 來源卡。L4 只當後端訊號發現機制（可餵進某張卡或某條 practiceChange），fetcher 保留不動。

**卡數軟目標（規則 A · 防太薄也防回頭填充）**：Tier-2 訊號卡目標 **3–5 張**。
- 真訊號 ≥3 則 → 有幾則寫幾張，**不封頂在 3**；強的獨立主題（如 AI-ECG／重要試驗）該給自己一張卡，不要硬折進別張卡的延伸。
- 真訊號 <3 則的**淡週** → **不可**用舊聞或補帶內容填充，改補**一張明確標示的「常青教學卡」**（board pearl／經典 case 重讀／一張值得回看的 ECG 圖／一個高頻陷阱複習），卡上標註「常青複習（非本週新訊號）」，讓淡週仍交付一個學習單位。
- **永遠禁止**：寫「本週無新訊號」硬撐、或把上週已寫過的東西換句話再寫一遍。

**配圖依卡型分兩類（規則 B · 修正上面「一律強制 ECG 圖／外連」）**：
- **case 卡**（討論一張特定 ECG）：**必附該 ECG**——能合法嵌 → `{{< figure-ecg >}}`；版權不能轉載 → `{{< ecg-linkout >}}` 標註「要看哪裡」＋跳原圖。**沒有可看的 ECG 就不寫這張 case 卡**。
- **研究／試驗／podcast／指引卡**（沒有單一 tracing）：用 `{{< ecg-linkout >}}` 當「來源預覽框」即可（anno 寫該則關鍵發現、linktext 連原始出處），**不強制單一 ECG 圖**。

> **訊號分類參考**（幫你判斷一則訊號屬哪個領域、避免重覆，非固定章節）：OMI / 急性冠症、節律 (AF/SVT/VT/電風暴)、傳導 (AV block/Mobitz/BBB)、通道病 (LQTS/Brugada/CPVT/早期再極化)、裝置 (Pacemaker/ICD/CRT/S-ICD)、消融 (Ablation/PFA/Cryo/STAR)、AI ECG / 穿戴、Resus / 急救、教學案例。毒物 + 心律 case（如 aconitine → polymorphic VT）歸「通道病」或「教學案例」。

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

**卡片內段落**：Tier-2 三句話（是什麼／為什麼要在意／所以呢）各自成段，不要黏成一大段，也不要在卡片外再寫獨立摘要段（摘要已濃縮進 front matter `subtitle`）。

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

Tier-3 延伸與出處（期刊速報）＋卡片引用中，作者 / 期刊 / 來源名英文後加繁中對照：

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

### 4. 策展數字（front matter，不再寫文末附錄 4 卡片）

不再產出 L1/L2/L3/L4 四張 source-card HTML 區塊（尤其**不產 L4 X.com 來源卡**）。改用 front matter 兩個整數欄位：

```python
import json
w = json.load(open('data/webscrape_cache.json'))   # L1
a = json.load(open('data/authors_cache.json'))     # L2
j = json.load(open('data/journals_cache.json'))    # L3
scanned = sum(len(x) for x in w.values()) + sum(len(x) for x in j.values()) + len(a)  # 誠實整數
picked  = <寫成卡片的張數>
```

`scanned` / `picked` 寫進 front matter，列表頁 list.html 自動渲染成「本週掃了 N 則，挑出 M 則」策展比一句話。

---

## 寫作風格

- **臺灣繁體中文**，禁簡體 / 大陸用語：
  - **OpenCC s2tw 只抓得到簡體字**，抓不到「同樣繁體字但用詞不同」的大陸用語
  - **同樣繁體字但用詞不同的常見大陸用語黑名單**（必須改成台灣寫法）：
    - 網絡 → 網路 ；視頻 → 影片 ；信息 → 資訊 ；計算機 → 電腦
    - 程序 → 程式 ；用戶 → 使用者 ；默認 → 預設 ；服務器 → 伺服器
    - 軟件 → 軟體 ；硬件 → 硬體 ；接口 → 介面 ；自定義 → 自訂
    - 算法 → 演算法 ；信號 → 訊號 ；響應 → 反應 / 回應 ；點擊 → 點選
    - 實時 → 即時 ；質量 → 品質（指 quality）；數據庫 → 資料庫
    - 心動過速 → 心搏過速（醫學）；心律失常 → 心律不整 ；心房纖顫 → 心房顫動
    - 室性心動過速 → 心室性心搏過速 ；體征 → 生命徵象 / 臨床徵象
    - 搭橋手術 → 繞道手術 ；超聲 → 超音波 ；彩超 → 心臟超音波
  - **跑兩道驗證**：(1) `opencc -c s2tw.json` 抓簡體字 (2) grep 上面黑名單確認沒漏
  - 台灣急診保留英文是常態（STEMI / cardiac arrest / cath lab / defibrillator），不是「中文寫不出來」就硬翻
- 醫學雜誌 editorial 語氣；每張 Tier-2 卡走「是什麼 → 為什麼要在意 → 所以呢」三句結構
- 英文術語保留（ECG、STEMI、OMI、NSTEMI、Sgarbossa、Wellens、De Winter、BRASH、LVH 等）
- 每個臨床主張**必附 footnote 出處**（不是只放連結，要 deep link 到「該主張對應的原文那一句」）
- 表格用 markdown，正確的 `|---|---|` 分隔線

## Footnote 引用鐵律（2026-04-30 加）

**目的**：讀者點 footnote 能直接跳到原文那句，做 fact-check。

**寫法**（Hugo goldmark footnote 支援）：

```markdown
這段內文寫了個臨床主張[^smith-04-23][^mattu-04-20]。

[^smith-04-23]: Magnus Nossen, "How would you interpret these T wave inversions?" — Dr Smith ECG Blog 2026-04-23：「[從原文摘出來的關鍵句]」 → [跳到原文](https://drsmithsecgblog.com/.../#:~:text=URL%20encoded%20原文片段)
[^mattu-04-20]: UMEM Cases Part 4 — ECG Weekly 2026-04-20：「[原文引用句]」 → [跳到原文](https://ecgweekly.com/.../#:~:text=URL%20encoded%20原文片段)
```

**規則**：
1. **每個臨床主張、每個 outcome 數據、每個試驗結論**都要 footnote
2. **多來源支撐同一主張** → 多個 footnote `[^a][^b]`（不要只標一個）
3. **footnote 內容必含三件事**：
   - **作者 / 出處 / 日期**（讀者掃一眼就知道引用哪篇）
   - **原文那一句**用「」包起來（中英都可，看原文是什麼）
   - **URL 加 Text Fragment** `#:~:text=...`，讓 Chrome / Edge 自動 highlight 跳到那句（Safari 從 17.4 開始也支援）
4. **Text Fragment 編碼**：用 Python `urllib.parse.quote()` 把原文片段 URL encode；空格變 `%20`、中文要 percent-encode；只取「夠唯一定位」的片段（10-30 字常足夠，太長反而 fail）
5. **資料來源對應 footnote 連結組成法**：
   - L1 web cache (`webscrape_cache.json`)：用 `url` + `summary` 摘關鍵句
   - L2 PubMed (`authors_cache.json`)：用 `https://pubmed.ncbi.nlm.nih.gov/{pmid}/` + `abstract` 摘
   - L3 CrossRef (`journals_cache.json`)：用 `https://doi.org/{doi}` + `abstract_digest` 摘
   - L4 X.com (`tweets.db`)：用 tweet `url` + `content` 整句（推文夠短直接用全文）
6. **footnote 集中放在文章最末**（H2 `## 引用` 區塊），不要散在每段下方
7. **footnote 編號格式**：用語意化 ID `[^smith-04-23]` `[^caan-af]` 不用流水號 `[^1]`，文件改動時不會錯亂
8. **footnote 是唯一逐句出處**，別把 reference 再重複塞進 Tier-3 延伸段或 front matter 策展數字（`scanned`/`picked` 只放計數，不放引用）

**Why**：之前週報只在段落中提「(Dr Smith 2026-04-23)」這種 inline citation，讀者看不到「這句到底是 Smith 的哪句」，要回去翻整篇 blog 才能 fact-check。Footnote + Text Fragment 讓引用變成「點一下就跳到那句的精準引用」。

**How to apply**：sub-agent 寫稿時每完成一段就同步在文末 `## 引用` 區塊補對應 footnote；不要寫完整篇才補（容易漏）。
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
