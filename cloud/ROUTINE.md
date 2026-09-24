# ER Cardio Weekly 雲端 routine 作業手冊

每週日由 Claude Code 雲端 routine 執行。你（雲端 Claude）從零開始，只照這份做。
**你的產出是一個 PR，不是上線。** 合併與上線由 Bear 在 GitHub 上決定。

## 0. 找到兩個 repo、決定週次

- 本 repo：`emergency-cardiology-weekly`（抓料程式＋本手冊）
- 部落格：`agoodbear.github.io`（Hugo 原始碼在 **`hugo-source` 分支**，不是 main）
- 用 `git rev-parse --show-toplevel`／`ls` 找出兩者路徑，下面以 `$ERCW`、`$BLOG` 代稱。
- 週次 `WEEK`：routine 指令有指定就用指定的；沒有就用台北時間今天所在 ISO 週：
  `TZ=Asia/Taipei python3 -c "from datetime import date;d=date.today();print(f'{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}')"`
- 若 `$BLOG` 的 `origin/hugo-source` 已有 `content/er-cardio-weekly/$WEEK/`，或已有開著的 `claude/ercw-$WEEK` 分支 → **停止**，回報「本週已存在」。

## 1. 安裝與抓料

```bash
bash $ERCW/cloud/setup.sh
export PATH="$HOME/.local/bin:$PATH"
cd $ERCW
for s in scrape authors journals; do uv run python main.py $s || echo "STAGE $s FAILED"; done
```
- **不跑 `fetch`（X.com）**：雲端沒有 X cookie，X 只是線索層，缺了不影響寫稿。
- 三層至少兩層成功才繼續；否則停止並回報哪幾層失敗與錯誤訊息（多半是網路白名單）。

## 2. 準備分支與 brief

```bash
cd $BLOG && git fetch origin hugo-source && git checkout -B claude/ercw-$WEEK origin/hugo-source
cd $ERCW && uv run python cloud/build_prompt.py --blog-repo $BLOG --week $WEEK --out cloud/out/brief.md
```
`cloud/out/brief.md` 的 `# SYSTEM` 段是寫稿規則，`# USER` 段是上一期內容與本週 cache。**完整讀完**再動筆。

## 3. 寫稿

- 依 brief 寫出 `$BLOG/content/er-cardio-weekly/$WEEK/index.md`（直接寫檔；front matter 開頭，不包 code fence）。
- `date` 用 brief 裡給的值；`scanned` 原樣照填；`picked` = Tier-2 卡數。
- 臺灣繁體中文、臺灣用語。中文與英文／數字之間**不加空格**。
- 讀者版面不得出現 X.com。

## 4. 醫學數字與引用查證（最高風險，不可省略）

對稿中**每一個**具體數字（樣本數、百分比、敏感度／特異度、HR/OR/CI、劑量、閾值、時間）與每一條引用：

1. **路徑一**：cache 裡該篇的摘要／原文片段。
2. **路徑二**：這次 session 用 WebFetch 或 curl **實際打開原文連結**（PubMed 頁、DOI、部落格原文）核對。
3. 兩條路徑一致 → 保留。不一致、打不開、或只有一條路徑 → **刪掉該數字**，或在文中寫「（待確認）」。**禁止憑記憶補數字。**
4. footnote 的 Text Fragment（`#:~:text=`）要對到原文實際存在的句子。

把查證結果整理成表（數字｜出處｜路徑一｜路徑二｜結果），放進 PR 內文。

## 5. 機械檢查（全部 PASS 才准 push）

```bash
cd $ERCW && uv run python cloud/finalize.py --blog-repo $BLOG --week $WEEK
```
FAIL 就修稿再跑，最多修 3 輪；3 輪仍 FAIL → 不 push，回報失敗原因。

## 6. 提交

```bash
cd $BLOG
git add content/er-cardio-weekly/$WEEK/index.md      # 只加這一個檔，禁止 git add 整個資料夾
git commit -m "ercw: $WEEK 週報草稿（雲端 routine）"
git push -u origin claude/ercw-$WEEK
```
推上 `claude/ercw-*` 分支後，GitHub Action（`ercw-auto-pr.yml`）會自動對 `hugo-source` 開 PR。
若你有能力直接開 PR，就自己開（base `hugo-source`），標題 `ER Cardio Weekly $WEEK`，內文含：
- 本週卡片清單（一行一張）
- 抓料結果（三層各幾則、失敗層）
- 第 4 步的查證表
- finalize 結果（zhtw 警告摘要、hugo build PASS）

**絕對不要**：push 到 `hugo-source` 或 `main`、合併 PR、改其他週的檔案、改版型／shortcode。

## 7. 最後回報

一段話：週次、卡數、PR／分支連結、查證中刪掉或標「待確認」的數字有幾個、任何失敗層。
