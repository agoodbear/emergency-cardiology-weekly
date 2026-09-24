# ER Cardio Weekly 雲端 routine 作業手冊

每週日由 Claude Code 雲端 routine 執行。你（雲端 Claude）從零開始，只照這份做。
**上線規則：你寫完 → 獨立查核代理通過 → 自動合併上線。查核沒過就不上線、PR 留給 Bear。**
Bear 不逐期審稿，所以第 4、5.5 步是唯一的品質閘門，不可省略、不可放水。

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

## 5.5 獨立查核（必做；由另一個代理做，不是你自己）

用 Agent 工具開一個新的子代理（model 用 opus），它**看不到你的寫稿過程**，只給它：稿件路徑、本手冊第 4 步的規則。交代它：
- 抽出稿中（含 front matter practiceChanges、footnote）**每一個**數字、閾值、統計、日期與引用主張。
- 每一項都**當場打開原文**核對（PubMed 用 `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=<PMID>&rettype=abstract&retmode=text`，要利益衝突聲明用 `retmode=xml` 找 `<CoiStatement>`；期刊頁 curl 被擋就改 WebFetch）。
- 檢查：數字是否相符、是否推論過頭（把單中心／單臂／案例寫成臨床指令）、`#:~:text=` 錨點句子是否真的在原文、**作者對所報導產品有無利益衝突且稿中有無揭露**。
- 不准用 Playwright 或瀏覽器自動化。
- 回傳：逐項表（項目｜稿中寫法｜原文引句｜URL｜相符／不符／無法開啟／過度推論／缺揭露）＋「必修清單」＋最後一行 `VERDICT=PASS` 或 `VERDICT=FAIL`。

處理結果：
- 必修項目由**你**修稿（不符的數字刪掉或改成原文；缺的揭露補上並附 footnote），修完重跑第 5 步 finalize。
- 修完後**再開一個新的查核代理**複查修過的地方。最多 2 輪。
- 最終 `VERDICT=PASS` 且 finalize PASS → 第 6 步帶 `[ercw-verified]`。否則不帶。

## 6. 提交

```bash
cd $BLOG
git add content/er-cardio-weekly/$WEEK/index.md      # 只加這一個檔，禁止 git add 整個資料夾
# 查核通過：
git commit -m "ercw: $WEEK 週報 [ercw-verified]"
# 查核未過：
# git commit -m "ercw: $WEEK 週報草稿（查核未過，待 Bear）"
git push -u origin claude/ercw-$WEEK
```
推上 `claude/ercw-*` 分支後，GitHub Action（`ercw-auto-pr.yml`）會自動開 PR；commit 訊息有 `[ercw-verified]` 就自動合併並觸發部署。
**你自己不要合併 PR、不要 push 到 `hugo-source` 或 `main`**，一律交給 Action。
有能力就更新 PR 內文（用繁中），內容：本週卡片清單、抓料結果、第 4 步查證表、第 5.5 步查核結論與修改紀錄、finalize 結果。

**絕對不要**：改其他週的檔案、改版型／shortcode／workflow。

## 7. 最後回報

**PR 內文、推播通知、最後回報一律用臺灣繁體中文。** 一段話：週次、卡數、是否帶 `[ercw-verified]`（會不會自動上線）、PR 連結、查證中刪掉或標「待確認」的數字有幾個、查核代理抓到並修掉什麼、任何失敗層。用推播通知送給 Bear。
