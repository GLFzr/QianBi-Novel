# -*- coding: utf-8 -*-
"""雷集 v2 框架 + 埋雷/去雷工具 + 摘要覆盖度断言的单测（W0.5 + W4.2）

覆盖：load_defects schema 校验、六维覆盖 ≥2、plant 工具 apply/strip 逐字节
round-trip、幂等（二次 apply 跳过）、--seed 可重放、check_rotation 轮换政策、
summary_assert 命中/缺失/退出码、对 v1 留存摘要的回放（文件缺失则跳过）。

全部离线：不触网、不调 LLM；子进程只跑两个 scripts 工具。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.planted_defects import (  # noqa: E402
    DIMS, DefectSchemaError, by_dim, check_rotation, coverage_report, load_defects,
)

PLANT = os.path.join(ROOT, "scripts", "plant_defects.py")
SUMMARY_ASSERT = os.path.join(ROOT, "scripts", "summary_assert.py")
# v1 留存摘要（只读回放用；tests_output 历史产物禁止删改，缺失则跳过该用例）
V1_SUMMARY = os.path.join(ROOT, "tests_output", "bench", "audit_hiflash",
                          "bench", "种子书", "追踪", "章节摘要.md")

# 假正文：仿种子书结构（标题行 + 空行分段），段 1/2 恰好满足 A01 的 replace_regex anchor
FAKE_A = (
    "# 第2章 半句话\n"
    "\n"
    "陈默在楼道口踩到那滩外卖汤渍，鞋底带起一串黏腻的声响。他蹲下看了两秒，跨过去，骑上共享单车。\n"
    "\n"
    "骑出巷口，手机在兜里震。房东的短信，一行字：账期到了，九千八。他按灭屏幕，风从城西旧巷子卷出来。\n"
    "\n"
    "回到出租屋已经三点过。父亲的东西一样样往外摆，他把那本种子书放进抽屉最里层。\n"
)
FAKE_B = (
    "# 第3章 一笔\n"
    "\n"
    "陈默在楼道口踩到那滩外卖汤渍，这回他没有停，直接跨了过去。周航的电动车斜停在单元门口。\n"
    "\n"
    "楼道里的感应灯坏了。他摸黑上楼，敲门，里面没人应。门缝底下压着一张水电催缴单。\n"
    "\n"
    "回到出租屋已经天黑。他把外卖单底联压在键盘下面，打开了那本种子书。\n"
)

ROUNDTRIP_IDS = ["A01", "A02", "B01", "F01"]  # 覆盖 replace_regex / after_title / before_end / at_end


def _run(args, cwd=None):
    """跑子进程（两脚本均为离线 CLI），统一 UTF-8 环境。"""
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, encoding="utf-8", cwd=cwd or ROOT, env=env)


def _make_drafts(tmp_path):
    d = tmp_path / "drafts"
    d.mkdir(parents=True)
    (d / "第002.md").write_text(FAKE_A, encoding="utf-8", newline="")
    (d / "第003.md").write_text(FAKE_B, encoding="utf-8", newline="")
    return str(d)


def _tree_bytes(drafts_dir):
    """目录内 第*.md 与 manifest 的逐字节快照（seed 重放对比用）。"""
    snap = {}
    for name in sorted(os.listdir(drafts_dir)):
        path = os.path.join(drafts_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                snap[name] = f.read()
    return snap


# ---------- 雷集 schema 与覆盖 ----------

def test_load_defects_schema_pass():
    data = load_defects()  # 校验失败会抛 DefectSchemaError
    assert data["version"] == 2
    assert len(data["defects"]) >= 12
    assert data["rotation"]["policy"] == "每2轮实验轮换30%"
    assert isinstance(data["rotation"]["history"], list)
    ids = [d["id"] for d in data["defects"]]
    assert len(ids) == len(set(ids))
    for d in data["defects"]:
        assert d["rule_ref"] and d["desc"] and d["inject"]["strip_hint"]
        assert d["verified_by"] == []  # 双人核验初始为空，待真人排期
        assert 30 <= len(d["inject"]["text"]) <= 120


def test_six_dim_coverage_at_least_two():
    data = load_defects()
    report = coverage_report(data)
    assert report["total"] >= 12
    assert report["missing"] == {}  # 六维每维 ≥2
    assert set(report["per_dim"]) == set(DIMS)
    assert report["legacy_v1"] == 4  # v1 四雷迁移入库
    groups = by_dim(data)
    assert sum(len(v) for v in groups.values()) == report["total"]


def test_legacy_v1_four_mines_present():
    groups = by_dim(load_defects())
    legacy = {d["id"]: d for dim in DIMS for d in groups[dim] if d.get("legacy_v1")}
    # v1 四雷：A 开章纯铺陈 / C 金手指对已发生事实落墨生效 / D 幻影引用 / F "他不知道的是"章尾
    assert set(legacy) == {"A01", "C01", "D01", "F01"}
    assert "晾衣绳上的水滴了七天" in legacy["A01"]["inject"]["text"]
    assert "让父亲在昨夜的高速上活下来" in legacy["C01"]["inject"]["text"]
    assert "老周" in legacy["D01"]["inject"]["text"]
    assert "他不知道的是" in legacy["F01"]["inject"]["text"]
    for d in legacy.values():
        assert "按 v1 报告描述重构" in d["desc"]


def test_all_four_inject_modes_covered():
    data = load_defects()
    modes = {d["inject"]["mode"] for d in data["defects"]}
    assert modes == {"after_title", "before_end", "at_end", "replace_regex"}


# ---------- 轮换政策 ----------

def test_check_rotation_policy():
    data = load_defects()
    ids = [d["id"] for d in data["defects"]]
    assert check_rotation(ids, rounds=1) == []  # 未到 2 轮不轮换
    rot = check_rotation(ids, rounds=2)
    n = math.ceil(0.3 * len(ids))
    assert len(rot) == n and set(rot) <= set(ids)
    assert check_rotation(ids, rounds=2) == rot  # 确定性（可重放）
    assert rot[0] == "A01"  # legacy_v1 优先轮换
    with pytest.raises(DefectSchemaError):
        check_rotation(["X99"])  # 雷集外 id 报错


# ---------- plant 工具：--list ----------

def test_plant_list_prints_dims():
    r = _run([PLANT, "--list"])
    assert r.returncode == 0
    for dim in DIMS:
        assert dim in r.stdout
    assert "A01" in r.stdout and "F03" in r.stdout
    assert "14 颗" in r.stdout


# ---------- plant 工具：apply/strip round-trip ----------

def test_apply_strip_roundtrip_byte_exact(tmp_path):
    drafts = _make_drafts(tmp_path)
    originals = _tree_bytes(drafts)

    r = _run([PLANT, "--drafts", drafts, "--defects", ",".join(ROUNDTRIP_IDS), "--apply", "--seed", "3"])
    assert r.returncode == 0, r.stdout + r.stderr
    # 4 雷 × 2 文件全部埋上
    assert r.stdout.count("[apply]") == len(ROUNDTRIP_IDS) * 2
    manifest_path = os.path.join(drafts, ".planted_manifest.json")
    assert os.path.isfile(manifest_path)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    assert len(manifest["planted"]) == len(ROUNDTRIP_IDS) * 2
    # 注入正文确实在文件里
    for name in ("第002.md", "第003.md"):
        text = open(os.path.join(drafts, name), encoding="utf-8").read()
        for d in load_defects()["defects"]:
            if d["id"] in ROUNDTRIP_IDS:
                assert d["inject"]["text"] in text
    # 开章已被换成铺陈（replace_regex 生效）
    a_text = open(os.path.join(drafts, "第002.md"), encoding="utf-8").read()
    assert "晾衣绳上的水滴了七天" in a_text
    assert "外卖汤渍" not in a_text  # 原开章段被整段替换

    # strip：按 manifest 逆向还原
    r2 = _run([PLANT, "--drafts", drafts, "--defects", ",".join(ROUNDTRIP_IDS), "--strip"])
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert r2.stdout.count("[ok]") == 2  # 两个文件均逐字节一致
    assert _tree_bytes(drafts) == originals  # 与注入前逐字节一致
    assert not os.path.isfile(manifest_path)  # 去净后 manifest 清空删除


def test_apply_idempotent_second_run_skips(tmp_path):
    drafts = _make_drafts(tmp_path)
    argv = [PLANT, "--drafts", drafts, "--defects", ",".join(ROUNDTRIP_IDS), "--apply", "--seed", "5"]
    assert _run(argv).returncode == 0
    first = _tree_bytes(drafts)
    r2 = _run(argv)
    assert r2.returncode == 0
    assert r2.stdout.count("[skip]") == len(ROUNDTRIP_IDS) * 2  # 二次 apply 全部跳过
    assert "[apply]" not in r2.stdout
    assert _tree_bytes(drafts) == first  # 文件未被再次改动
    manifest = json.load(open(os.path.join(drafts, ".planted_manifest.json"), encoding="utf-8"))
    assert len(manifest["planted"]) == len(ROUNDTRIP_IDS) * 2  # manifest 不重复记录


def test_apply_seed_replayable(tmp_path):
    defects_arg = ["--defects", ",".join(ROUNDTRIP_IDS), "--apply", "--seed", "7"]
    dir1, dir2 = _make_drafts(tmp_path / "run1"), _make_drafts(tmp_path / "run2")
    assert _run([PLANT, "--drafts", dir1] + defects_arg).returncode == 0
    assert _run([PLANT, "--drafts", dir2] + defects_arg).returncode == 0
    assert _tree_bytes(dir1) == _tree_bytes(dir2)  # 同 seed 两次 apply 产物（含 manifest）逐字节一致
    # 不同注入顺序会改变产物（证明 shuffle 真的在起作用）——不同 seed 的 after_title 排序应可能不同，
    # 此处只断言同 seed 稳定，不冒进断言异 seed 必异。


def test_anchor_partial_hit_warns_zero_hit_fails(tmp_path):
    """内容锚点雷（A01）：命中部分文件=warn 且退出 0；零落点=退出 1。"""
    d = _make_drafts(tmp_path)  # 两份假正文都带锚点
    # 删掉 003 的锚点段 → A01 只落 002
    p3 = os.path.join(d, "第003.md")
    open(p3, "w", encoding="utf-8", newline="").write(
        "# 第3章 一笔\n\n楼道里的感应灯坏了。他摸黑上楼，敲门，里面没人应。\n\n"
        "回到出租屋已经天黑。他把外卖单底联压在键盘下面。\n")
    r = _run([PLANT, "--drafts", d, "--defects", "A01", "--apply"])
    assert r.returncode == 0
    assert r.stdout.count("[warn]") == 1 and r.stdout.count("[apply]") == 1
    # 两份都不带锚点 → 零落点，退出 1
    d2 = tmp_path / "no_anchor"
    (d2 / "drafts").mkdir(parents=True)
    open(os.path.join(str(d2), "drafts", "第004.md"), "w", encoding="utf-8", newline="").write(
        "# 第4章 无锚\n\n这一章从头到尾都没有锚点段。\n\n只有普普通通的两段正文。\n")
    r2 = _run([PLANT, "--drafts", str(d2 / "drafts"), "--defects", "A01", "--apply"])
    assert r2.returncode == 1
    assert "没有落到任何草稿上" in r2.stdout


def test_apply_strip_roundtrip_crlf(tmp_path):
    """CRLF 草稿（v1 bench 草稿即 CRLF）同样逐字节 round-trip。"""
    d = tmp_path / "drafts_crlf"
    d.mkdir()
    crlf_a = FAKE_A.replace("\n", "\r\n")
    crlf_b = FAKE_B.replace("\n", "\r\n")
    (d / "第002.md").write_text(crlf_a, encoding="utf-8", newline="")
    (d / "第003.md").write_text(crlf_b, encoding="utf-8", newline="")
    drafts = str(d)
    originals = _tree_bytes(drafts)
    r = _run([PLANT, "--drafts", drafts, "--defects", ",".join(ROUNDTRIP_IDS),
              "--apply", "--seed", "1"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("[apply]") == len(ROUNDTRIP_IDS) * 2  # 两份假正文都带 A01 锚点段
    assert "[warn]" not in r.stdout
    r2 = _run([PLANT, "--drafts", drafts, "--strip"])
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert _tree_bytes(drafts) == originals  # CRLF 逐字节一致


# ---------- summary_assert（W4.2） ----------

MANIFEST_HIT = {
    "characters": [{"key": "陈默", "aliases": ["老陈"]}],
    "events": [{"key": "通话录音", "aliases": ["录音"]}],
    "timeline": [{"key": "0317", "aliases": ["编号零三一七"]}],
}
SUMMARY_TEXT = ("陈默回出租屋整理遗物，拨父亲手机号时触发未播放的通话录音，听到半句嘱托被门铃掐断；"
                "比对底噪外卖订单播报的编号零三一七与外卖单底联单号二次叠合。")


def test_summary_assert_all_hit_exit_zero(tmp_path):
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(MANIFEST_HIT, ensure_ascii=False), encoding="utf-8")
    spath = tmp_path / "summary.md"
    spath.write_text(SUMMARY_TEXT, encoding="utf-8")
    r = _run([SUMMARY_ASSERT, "--summary", str(spath), "--manifest", str(mpath)])
    assert r.returncode == 0
    assert "全部命中" in r.stdout and "3/3" in r.stdout
    # 别名也能命中（key 未出现时）
    assert "编号零三一七" in r.stdout


def test_summary_assert_missing_exit_one(tmp_path):
    manifest = json.loads(json.dumps(MANIFEST_HIT, ensure_ascii=False))
    manifest["events"].append({"key": "不存在的事件", "aliases": ["查无此事"]})
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = _run([SUMMARY_ASSERT, "--summary-text", SUMMARY_TEXT, "--manifest", str(mpath)])
    assert r.returncode == 1
    assert "未命中" in r.stdout and "存在缺失" in r.stdout


def test_summary_assert_bad_usage_exit_two(tmp_path):
    r = _run([SUMMARY_ASSERT, "--summary-text", "x", "--inline", "{不是json"])
    assert r.returncode == 2


@pytest.mark.skipif(not os.path.isfile(V1_SUMMARY), reason="v1 留存摘要不存在（tests_output 被清理时跳过）")
def test_summary_assert_replay_v1_kept_summary(tmp_path):
    """W4.2 DoD：对 v1 留存摘要回放通过（只读 tests_output，不改动）。"""
    text = open(V1_SUMMARY, encoding="utf-8").read()
    manifest = {
        "characters": [{"key": "陈默", "aliases": []}, {"key": "林兰", "aliases": []},
                       {"key": "周航", "aliases": []}],
        "events": [{"key": "通话录音", "aliases": ["录音"]}, {"key": "种子书", "aliases": []}],
        "timeline": [{"key": "0317", "aliases": ["零三一七"]}, {"key": "3月17日", "aliases": []}],
    }
    mpath = tmp_path / "v1_manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = _run([SUMMARY_ASSERT, "--summary", V1_SUMMARY, "--manifest", str(mpath)])
    assert r.returncode == 0, r.stdout
    assert "全部命中" in r.stdout


# ---------- schema 校验的负例（防雷集被改坏后静默通过） ----------

def test_load_defects_rejects_broken_schema(tmp_path):
    data = load_defects()
    bad = json.loads(json.dumps(data))
    bad["defects"][0]["id"] = bad["defects"][1]["id"]  # id 重复
    p = tmp_path / "bad1.json"
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DefectSchemaError):
        load_defects(str(p))

    bad2 = json.loads(json.dumps(data))
    bad2["defects"] = [d for d in bad2["defects"] if d["dim"] != "E_CHARACTER"]  # E 维清零
    p2 = tmp_path / "bad2.json"
    p2.write_text(json.dumps(bad2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DefectSchemaError):
        load_defects(str(p2))
