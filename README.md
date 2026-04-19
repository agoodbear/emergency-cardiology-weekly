# 急診心臟學週報（Emergency Cardiology Weekly）

自動生成急診 ECG / 心臟學每週趨勢報告，以繁體中文撰寫（英文醫學名詞保留原文）。

目前主題：**急診 ECG / 心臟學**（OMI/STEMI、arrhythmia、conduction、channelopathy、裝置與 ablation、AI ECG、穿戴裝置、resuscitation）

資料來源：
- **教學 blog**：Dr Smith ECG Blog、ECG Weekly (Amal Mattu)、LITFL ECG Library、EMCrit、REBEL EM、First10EM、ALiEM、Core EM
- **學會 / 官方**：ACC、ESC、HRS、AHA（via Google News）
- **期刊**：Heart Rhythm、JACC-EP、Circulation-AE、Journal of Electrocardiology、Annals of Emergency Medicine、Resuscitation（via CrossRef API）
- **Twitter KOL**（選用）：smithECGBlog、amalmattu、EMSwami、EMCrit、srrezaie、HRSonline、escardio...

週報風格：**醫學雜誌 editorial**——每章導言 → 3-4 重點 → Bottom line，3 分鐘讀完。

最新週報範例：[2026-W16](https://github.com/agoodbear/emergency-cardiology-weekly/blob/main/reports/2026-W16.md)

---

## 快速開始

```bash
# 1. 安裝 uv（Python 套件管理）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或： brew install uv

# 2. 安裝相依套件
uv sync

# 3. 執行爬蟲（11 個 web sources）
uv run python main.py scrape

# 4. 執行期刊抓取（CrossRef 6 本期刊）
uv run python main.py journals

# 5. 檢視結果
cat data/webscrape_cache.json | python3 -m json.tool | less
cat data/journals_cache.json | python3 -m json.tool | less
```

週報本身由 Claude Code 在 session 中讀 cache 後手寫產出（見 `CLAUDE.md`）——Python 負責抓料，Claude 負責策展與敘事。

Push `reports/YYYY-WNN.md` 到 `main` 後，GitHub Action 自動發佈到 Wiki。

---

## 專案結構

```
.
├── source/                   ← 所有主題相關參數（不需改 Python）
│   ├── keywords.yml          ← ECG / 心臟學關鍵詞（過濾與 tag 用）
│   ├── drug_groups.yml       ← 主題分組（OMI、arrhythmia、conduction...）
│   ├── search_queries.yml    ← Twitter 搜尋 query
│   ├── web_sources.yml       ← 爬蟲來源（RSS / Google News / ECG Weekly）
│   ├── journals.yml          ← CrossRef 期刊 ISSN 清單
│   └── twitter.yml           ← Twitter GraphQL op_id、cookie skip
├── config/
│   └── seeds.txt             ← KOL Twitter 帳號種子
├── src/
│   ├── config.py             ← YAML 載入器
│   ├── webscraper.py         ← RSS / Google News / ECG Weekly 爬蟲
│   ├── crossref_fetcher.py   ← CrossRef 期刊 API
│   ├── fetcher.py            ← Twitter 爬蟲（選用）
│   ├── reporter.py           ← Twitter 聚合報告（選用）
│   ├── discover.py           ← KOL 自動發掘（選用）
│   └── db.py                 ← SQLite 儲存
├── reports/                  ← 產出的週報（push 即觸發 wiki 發布）
│   └── _archive/             ← 歷史資料（不進 wiki）
├── CLAUDE.md                 ← Claude Code 寫報告的 SOP
├── main.py                   ← CLI 入口
└── .github/workflows/
    └── publish-wiki.yml      ← 自動發佈 wiki 的 GitHub Action
```

---

## 如何切換至其他主題

本系統沿用 upstream 的 **topic-agnostic** 架構——所有領域知識都集中在 `source/*.yml` 和 `config/seeds.txt`，切換主題只需改這六個檔案，**不需動 Python**。

若要從 ECG 切到其他主題（例如中風、糖尿病、急性呼吸衰竭）：

1. **`source/keywords.yml`**：改成新主題關鍵詞（YAML 根 key 是 `topic_keywords`，列你主題的關鍵字即可）
2. **`source/drug_groups.yml`**：重寫主題分組 + `conference_keywords`
3. **`source/search_queries.yml`**：改 Twitter 搜尋 query
4. **`source/web_sources.yml`**：改 RSS / Google News 來源；Google News 可用 `query:` 欄位覆蓋預設搜尋字串
5. **`source/journals.yml`**：改 CrossRef ISSN 清單（`bc_filter` 欄位名保留）
6. **`config/seeds.txt`**：改 KOL Twitter handle

若新主題需要客製爬蟲（像本專案的 `ECG Weekly` preview fetcher），在 `web_sources.yml` 加新 `type:`，在 `src/webscraper.py` 對應加新 fetcher function。

---

## 常見維護任務

| 問題 | 解法 |
|------|------|
| 某個 RSS 突然沒抓到新文章 | 檢查來源首頁 HTML 有沒有 `canonical` 或 `meta refresh`，可能已搬家（Dr Smith 就遇過這狀況） |
| 關鍵字 substring 誤中（如 AF 匹配 after）| 確認 `webscraper.py` / `crossref_fetcher.py` 的 word-boundary regex 還在作用 |
| Twitter API 回 404 | 更新 `source/twitter.yml` 的 `op_id`（抓 x.com main.*.js 裡的 SearchTimeline operation ID） |
| 某主題關鍵字沒被捕捉 | 加進 `keywords.yml` 和對應 `drug_groups.yml` |
| 新增爬蟲來源 | 在 `web_sources.yml` 加一筆 `type: rss` 或 `type: google_news` |
| Wiki 沒更新 | 確認 push 包含 `reports/*.md`；或手動跑 Actions → Workflow dispatch |

---

## GitHub Actions — Wiki 自動發佈

每次 push 包含 `reports/*.md` 的 commit 到 `main`，`.github/workflows/publish-wiki.yml` 自動：

1. 把新報告複製到 wiki repo
2. 重建 `Home.md` 索引（最新在前）
3. Push 到 wiki `master` branch

**首次使用需要手動初始化 wiki**：前往 [wiki 頁面](https://github.com/agoodbear/emergency-cardiology-weekly/wiki) 點 **Create the first page** 隨意存一頁，之後 workflow 就能自動發佈。

手動觸發：Actions → **Publish Reports to Wiki** → **Run workflow**

---

## 發佈管線（Phase 2 規劃）

目前 Wiki 是過渡方案。Phase 2 將把內容發佈管線改為：

1. **主站**：獨立 Hugo 站「急診週報」（視覺設計走 Claude Design → Claude Code 實作）
2. **個人知識庫**：Roam daily note 加 `[[急診週報]]` tag
3. **推播**：Discord thread 貼週報標題 + 連結
4. **備份**：GitHub repo 的 `reports/*.md`

---

## 致謝

本專案 fork 自 [htlin222/breast-cancer-uptodate](https://github.com/htlin222/breast-cancer-uptodate)——感謝 [@htlin222](https://github.com/htlin222)（林煌騰醫師）建立 topic-agnostic 的週報生成架構。他設計了所有領域知識都集中在 YAML 的優雅分離方式，讓「換主題不用改程式」成為現實，本專案從 breast cancer oncology 切到 emergency cardiology 只改了六個 YAML 加兩處 Python patch。

---

## 作者

**曹建雄** — 宜蘭陽明交通大學附設醫院 急診科主治醫師
- 個人網站：[agoodbear.github.io](https://agoodbear.github.io/)
- GitHub：[@agoodbear](https://github.com/agoodbear)

---

## 授權

MIT
