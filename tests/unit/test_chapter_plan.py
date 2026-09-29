# -*- coding: utf-8 -*-
"""B7 章节计划三槽位 next/near/far（app/core/tracking_store.py 计划表区）

- 三槽位 CRUD：plan_set_next（UPSERT/空白清空）、plan_add_near/far（同文幂等）
- plan_consume 定稿流转：next 清空出册、near[0] 升格为 next、其余前移、far
  不动；consumed 日志保同章重写重定稿幂等（不二次升格）
- plan_query / render_for_outline：next 必写、near 参考、far 远景；三槽位全空
  → "" 不注入（证据在场才注入）；max_chars 预算截断
- fail-open：sidecar 缺失/损坏按空计划、读路径零副作用、坏字段形态逐项丢弃、
  坏章号 no-op、追踪/ 目录缺失自动建
全部 tmp_path 真实文件，纯本地零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import tracking_store as ts


def _proj(tmp_path, name="书"):
    proj = str(tmp_path / name)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    return proj


def _plan_path(proj):
    return os.path.join(proj, "追踪", "章节计划.json")


def _read_plan(proj):
    with open(_plan_path(proj), encoding="utf-8") as f:
        return json.load(f)


# ---------------- 装载与查询 ----------------

def test_load_default_zero_side_effect(tmp_path):
    """缺失 sidecar → 空计划，且读路径零副作用（不回写文件）"""
    proj = _proj(tmp_path)
    assert ts.load_chapter_plan(proj) == {
        "version": 1, "next": None, "near": [], "far": [], "consumed": []}
    assert not os.path.exists(_plan_path(proj))
    assert ts.plan_query(proj) == {"next": None, "next_source_ch": None,
                                   "near": [], "far": []}
    assert ts.render_for_outline(proj) == ""          # 全空 → "" 零注入


def test_query_shape(tmp_path):
    proj = _proj(tmp_path)
    ts.plan_set_next(proj, "雨夜追凶", source_ch=12)
    ts.plan_add_near(proj, "茶楼初遇", target_ch=15)
    ts.plan_add_far(proj, "北境线终局")
    q = ts.plan_query(proj)
    assert q["next"] == "雨夜追凶" and q["next_source_ch"] == 12
    assert q["near"] == [{"content": "茶楼初遇", "target_ch": 15}]
    assert q["far"] == [{"content": "北境线终局"}]


# ---------------- 三槽位 CRUD ----------------

def test_set_next_upsert_and_clear(tmp_path):
    proj = _proj(tmp_path)
    nxt = ts.plan_set_next(proj, "主角发现令牌之秘", source_ch=12)
    assert nxt == {"content": "主角发现令牌之秘", "source_ch": 12}
    # UPSERT 覆盖；source_ch 缺省 → None
    assert ts.plan_set_next(proj, "换计划：雨夜追凶") == {
        "content": "换计划：雨夜追凶", "source_ch": None}
    assert ts.load_chapter_plan(proj)["near"] == []
    # 空白 → 清空
    assert ts.plan_set_next(proj, "   ") is None
    assert ts.load_chapter_plan(proj)["next"] is None
    # 非法 source_ch 类型 fail-open 归 None，不抛
    assert ts.plan_set_next(proj, "x", source_ch="第x章")["source_ch"] is None


def test_add_near_far_dedupe(tmp_path):
    proj = _proj(tmp_path)
    ts.plan_add_near(proj, "茶楼初遇", target_ch=15)
    ts.plan_add_near(proj, "无章号计划")
    # 同文幂等：只更新 target_ch，不重复追加
    hit = ts.plan_add_near(proj, "茶楼初遇", target_ch=16)
    near = ts.load_chapter_plan(proj)["near"]
    assert len(near) == 2
    assert hit["target_ch"] == 16 and near[0]["target_ch"] == 16
    assert near[1] == {"content": "无章号计划", "target_ch": None}
    # 非法 target_ch 类型 fail-open 归 None
    assert ts.plan_add_near(proj, "新条目", target_ch="第x章")["target_ch"] is None
    # far 追加 + 同文幂等 + 空白忽略
    ts.plan_add_far(proj, "北境线终局")
    assert ts.plan_add_far(proj, "北境线终局") == {"content": "北境线终局"}
    assert ts.plan_add_far(proj, "   ") is None
    assert ts.load_chapter_plan(proj)["far"] == [{"content": "北境线终局"}]


# ---------------- plan_consume 定稿流转 ----------------

def test_consume_flow(tmp_path):
    proj = _proj(tmp_path)
    ts.plan_set_next(proj, "雨夜追凶", source_ch=12)
    ts.plan_add_near(proj, "茶楼初遇", target_ch=15)
    ts.plan_add_near(proj, "密室线索", target_ch=16)
    ts.plan_add_far(proj, "北境线终局")
    out = ts.plan_consume(proj, 13)
    assert out == {"cleared": "雨夜追凶", "promoted": "茶楼初遇", "skipped": False}
    d = ts.load_chapter_plan(proj)
    assert d["next"] == {"content": "茶楼初遇", "source_ch": 13}
    assert [e["content"] for e in d["near"]] == ["密室线索"]
    assert d["far"] == [{"content": "北境线终局"}]      # far 不动
    assert d["consumed"] == [13]
    # 继续定稿：逐章前移
    assert ts.plan_consume(proj, 14) == {
        "cleared": "茶楼初遇", "promoted": "密室线索", "skipped": False}
    assert ts.load_chapter_plan(proj)["near"] == []
    # near 耗尽：next 清空、无升格，far 仍不动
    assert ts.plan_consume(proj, 15) == {
        "cleared": "密室线索", "promoted": None, "skipped": False}
    d = ts.load_chapter_plan(proj)
    assert d["next"] is None
    assert d["consumed"] == [13, 14, 15]
    assert d["far"] == [{"content": "北境线终局"}]


def test_consume_idempotent_and_bad_num(tmp_path):
    proj = _proj(tmp_path)
    ts.plan_set_next(proj, "A", source_ch=9)
    ts.plan_add_near(proj, "B")
    assert ts.plan_consume(proj, 10)["promoted"] == "B"
    # 同章重写重定稿 → 幂等跳过，不二次升格
    assert ts.plan_consume(proj, 10) == {
        "cleared": None, "promoted": None, "skipped": True}
    d = ts.load_chapter_plan(proj)
    assert d["next"] == {"content": "B", "source_ch": 10}
    assert d["consumed"] == [10]
    # 坏章号 no-op（fail-open）
    assert ts.plan_consume(proj, "第x章")["skipped"] is True
    assert ts.plan_consume(proj, None)["skipped"] is True
    assert ts.load_chapter_plan(proj)["consumed"] == [10]


# ---------------- render_for_outline ----------------

def test_render_for_outline(tmp_path):
    proj = _proj(tmp_path)
    ts.plan_set_next(proj, "雨夜追凶", source_ch=12)
    ts.plan_add_near(proj, "茶楼初遇", target_ch=15)
    ts.plan_add_near(proj, "密室对峙")                 # 无章号：只排不滤，无章注
    ts.plan_add_far(proj, "北境线终局")
    ts.plan_add_far(proj, "师门旧案")
    text = ts.render_for_outline(proj)
    assert text.startswith("【章节计划】")
    assert "next=下一章必写" in text and "near=近期参考" in text and "far=远景方向" in text
    assert "- 必写（next）：雨夜追凶（第12章登记）" in text
    assert "- 近期（near）：约第15章 茶楼初遇；密室对峙" in text
    assert "- 远景（far）：北境线终局；师门旧案" in text
    # 展示上限：near/far 各取前 _NEAR/_FAR_RENDER_CAP 条（此前已各占 2 席）
    for i in range(10):
        ts.plan_add_near(proj, "近期条目%d" % i, target_ch=20 + i)
        ts.plan_add_far(proj, "远景条目%d" % i)
    text = ts.render_for_outline(proj)
    assert "近期条目%d" % (ts._NEAR_RENDER_CAP - 3) in text
    assert "近期条目%d" % (ts._NEAR_RENDER_CAP - 2) not in text
    assert "远景条目%d" % (ts._FAR_RENDER_CAP - 3) in text
    assert "远景条目%d" % (ts._FAR_RENDER_CAP - 2) not in text
    # 预算截断：装不下的行整行丢弃（头行恒在；头行语义词不计入——断言槽位行前缀）
    short = ts.render_for_outline(proj, max_chars=40)
    assert short.startswith("【章节计划】")
    assert "- 必写（next）：" not in short and "- 近期（near）：" not in short \
        and "- 远景（far）：" not in short
    assert len(short) < len(text)


# ---------------- fail-open ----------------

def test_fail_open_corrupted_and_autocreate(tmp_path):
    proj = _proj(tmp_path)
    # 损坏 JSON → 空计划，不抛
    with open(_plan_path(proj), "w", encoding="utf-8") as f:
        f.write("{next: 坏json")
    assert ts.load_chapter_plan(proj)["next"] is None
    assert ts.plan_query(proj) == {"next": None, "next_source_ch": None,
                                   "near": [], "far": []}
    # 损坏册上写路径照常工作（重建合法册）
    ts.plan_set_next(proj, "重建", source_ch=1)
    assert ts.load_chapter_plan(proj)["next"]["content"] == "重建"
    # 损坏字段形态 fail-open：next 非字典/空内容、条目非字典、章号非 int 逐项丢弃
    with open(_plan_path(proj), "w", encoding="utf-8") as f:
        json.dump({"version": 1,
                   "next": {"content": "  "},
                   "near": ["垃圾", {"content": "好条目", "target_ch": "x"},
                            {"content": ""}],
                   "far": [{"nonsense": 1}, 42, {"content": "好远景"}],
                   "consumed": ["x", 3, 1.2]},
                  f, ensure_ascii=False)
    q = ts.plan_query(proj)
    assert q["next"] is None
    assert q["near"] == [{"content": "好条目", "target_ch": None}]
    assert q["far"] == [{"content": "好远景"}]
    assert ts.load_chapter_plan(proj)["consumed"] == [3]
    # 追踪/ 目录整体缺失 → 写路径自动建目录
    fresh = str(tmp_path / "新书")
    ts.plan_set_next(fresh, "首计划", source_ch=1)
    assert ts.load_chapter_plan(fresh)["next"]["content"] == "首计划"
