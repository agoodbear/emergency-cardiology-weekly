"""cloud/build_prompt.py 與 cloud/finalize.py：週次計算、cache 裁切、上線前機械檢查。"""
import json

import pytest

from conftest import load_script

bp = load_script("cloud/build_prompt.py", "build_prompt")
fz = load_script("cloud/finalize.py", "finalize")


# ── 週次 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cur,prev", [
    ("2026-W45", "2026-W44"),
    ("2027-W01", "2026-W53"),   # 2026 是 53 週年（1/1 是週四）
    ("2026-W01", "2025-W52"),
])
def test_previous_week_label_year_boundary(cur, prev):
    assert bp.previous_week_label(cur) == prev


def test_week_range_for_label():
    assert bp.week_range_for_label("2026-W45") == ("2026-11-02", "2026-11-08")
    assert bp.week_range_for_label("2026-W53") == ("2026-12-28", "2027-01-03")


def test_iso_week_label_uses_iso_year_not_calendar_year():
    from datetime import datetime
    # 2027-01-01 屬於 2026-W53；用 d.year 會錯成 2027-W53
    assert bp.iso_week_label(datetime(2027, 1, 1)) == "2026-W53"


# ── cache 裁切 / scanned ─────────────────────────────────────────────────────

def test_truncate_layer_round_robin_keeps_every_key():
    data = {"A": [{"t": "x" * 200} for _ in range(20)], "B": [{"t": "y" * 200}], "C": []}
    out = bp._truncate_layer(data, 1500)
    assert bp._dump_len(out) <= 1500
    assert out["B"], "round-robin 應保證小 key 不被大 key 吃光"
    assert 0 < len(out["A"]) < 20
    assert out["C"] == []


def test_truncate_layer_within_budget_is_identity():
    data = {"A": [1, 2]}
    assert bp._truncate_layer(data, 10_000) is data


def test_truncate_list_layer_never_exceeds_budget():
    data = [{"t": "z" * 100} for _ in range(50)]
    out = bp._truncate_layer(data, 1000)
    assert bp._dump_len(out) <= 1000 and len(out) < 50


def test_compute_scanned_counts_items_and_ignores_errors():
    bundle = {"L1_web": {"a": [1, 2], "b": [3]},
              "L2_pubmed": {"Smith": [1], "Meyers": [1, 2]},
              "L3_crossref": {"_error": "missing file"}}
    total, detail = bp.compute_scanned(bundle)
    assert total == 6
    assert detail == "L1=3 + L3=0 + L2=3"


def test_build_prompt_injects_date_and_scanned(tmp_path):
    bundle = {"L1_web": {"a": [{"title": "t"}]}, "L2_pubmed": {}, "L3_crossref": {}}
    system, user = bp.build_prompt("2026-W45", "2026-W44", bundle, "(prev)", "2026-11-02", "2026-11-08")
    assert 'slug: "2026-W45"' in system
    assert "scanned: 1 " in system
    assert "+08:00" in system            # 時區冒號已補上
    assert "kind=\"retro\"" not in system.replace('kind="retro"**', "")  # 範例不能寫錯語法
    assert json.dumps({"title": "t"}, ensure_ascii=False, indent=2).splitlines()[1].strip() in user


# ── finalize ─────────────────────────────────────────────────────────────────

GOOD = """---
title: "標題"
subtitle: "副標"
shortTitle: "短標"
slug: "2026-W45"
week: "2026-W45"
weekRange: "2026-11-02 — 2026-11-08"
date: 2026-11-08T10:00:00+08:00
scanned: 120
picked: 2
practiceChanges:
  - text: "a"
  - text: "b"
  - text: "c"
sections: []
---

## 卡一 {#s1}

{{< grade "回溯 · n=17" kind="retro" >}}

## 卡二 {#s2}

本文
"""


def test_sanitize_grade_named_param():
    fixed, notes = fz.sanitize_shortcodes(GOOD)
    assert '{{< grade "回溯 · n=17" "retro" >}}' in fixed
    assert notes == ["grade kind= 具名參數 → 位置參數 ×1"]


def test_good_article_passes_after_sanitize():
    fixed, _ = fz.sanitize_shortcodes(GOOD)
    assert fz.validate_front_matter(fixed, "2026-W45") == []
    assert fz.extra_checks(fixed, "2026-W45") == []


def test_picked_mismatch_and_wrong_week():
    art = GOOD.replace("picked: 2", "picked: 3").replace('week: "2026-W45"', 'week: "2026-W44"')
    probs = fz.extra_checks(art, "2026-W45")
    assert any("picked=3" in p for p in probs)
    assert "week != 2026-W45" in probs


def test_x_com_link_is_rejected():
    art = GOOD + "\n[推文](https://x.com/smithECGBlog/status/1)\n"
    assert any("X.com" in p for p in fz.extra_checks(art, "2026-W45"))


def test_practice_changes_count():
    art = GOOD.replace('  - text: "c"\n', "")
    assert any("practiceChanges" in p for p in fz.extra_checks(art, "2026-W45"))


def test_missing_front_matter_and_empty_body():
    assert fz.validate_front_matter("no front matter", "2026-W45") == ["missing or unclosed front matter"]
    head = GOOD.split("\n---\n")[0] + "\n---\n"
    assert "empty article body" in fz.validate_front_matter(head, "2026-W45")


def test_invalid_yaml_reports_instead_of_crashing():
    bad = "---\ntitle: [unclosed\n---\n\nbody\n"
    assert fz.validate_front_matter(bad, "2026-W45")[0].startswith("invalid YAML")
    # extra_checks 以前會在這裡丟 yaml.YAMLError，讓 finalize 直接 traceback
    probs = fz.extra_checks(bad, "2026-W45")
    assert probs and all(isinstance(p, str) for p in probs)
