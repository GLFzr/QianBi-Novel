# -*- coding: utf-8 -*-
"""Agent 应用操作工具层：指令解析 + 工具执行（含微循环兼容验证）"""
import os

import pytest

from app import project
from app.core import agent_tools as at
from app.core import state as st
from app.core import stages


# ---------- 指令解析 ----------

@pytest.mark.parametrize("text,tool", [
    ("回退到去味之前", "rollback_step"),
    ("重跑第4章审校", "rollback_step"),
    ("从审校重新来", "rollback_step"),
    ("重新生成第3章的细纲", "regen_outline"),
    ("第3章细纲重新生成", "regen_outline"),
    ("重写第2章，铺垫再足一点", "rewrite_chapter"),
    ("看看第3章正文", "read_chapter"),
    ("现在进度怎么样", "status"),
    ("关闭人工审校", "set_setting"),
    ("开启连写模式", "set_setting"),
    ("/状态", "status"),
])
def test_parse_instruction_rules(text, tool):
    r = at.parse_instruction(text, default_chapter=5)
    assert r is not None and r[0] == tool, (text, r)


@pytest.mark.parametrize("text", ["今天天气不错", "这一章的爽点不够足，主角太被动了"])
def test_parse_instruction_ignores_plain_text(text):
    assert at.parse_instruction(text, default_chapter=5) is None


def test_parse_rollback_step_mapping():
    assert at.parse_instruction("回退到去味之前")[1]["to_step"] == "deslop"
    assert at.parse_instruction("重写草稿")[1]["to_step"] == "draft"
    assert at.parse_instruction("回退到审校之前")[1]["to_step"] == "review"


def test_parse_rewrite_carries_guidance():
    r = at.parse_instruction("重写第2章，铺垫再足一点，节奏慢一些")
    assert r[0] == "rewrite_chapter"
    assert r[1]["chapter"] == 2
    assert "铺垫" in r[1]["guidance"]


def test_parse_forced_prefix_is_exact():
    r = at.parse_instruction("/状态")
    assert r[2] == "exact"


# ---------- 工具执行 ----------

def _mk_proj(tmp_path):
    proj = tmp_path / "工具书"
    for d in ("设定", "大纲", "正文", "追踪"):
        (proj / d).mkdir(parents=True)
    (proj / "设定" / "题材定位.md").write_text("# 题材定位\n测试", encoding="utf-8")
    (proj / "大纲" / "细纲_第001章.md").write_text("核心事件：测试", encoding="utf-8")
    (proj / "正文" / "第001章_测试.md").write_text("# 第1章 测试\n\n" + "正文内容。" * 100,
                                                    encoding="utf-8")
    return str(proj)


def test_status_reads_pipeline(tmp_path):
    proj = _mk_proj(tmp_path)
    res = at.execute("status", {}, proj, {})
    assert res["ok"] and "共 1 章" in res["message"]


def test_read_chapter(tmp_path):
    proj = _mk_proj(tmp_path)
    res = at.execute("read_chapter", {"chapter": 1}, proj, {})
    assert res["ok"] and "正文内容" in res["message"]
    res = at.execute("read_chapter", {"chapter": 9}, proj, {})
    assert not res["ok"]


def test_rollback_step_sets_checkpoint(tmp_path):
    proj = _mk_proj(tmp_path)
    st.save_chapter_step(proj, 1, step_done="review", draft_path="正文/.drafts/第001.md",
                         votes=[{"x": 1}], outline_fp="abc")
    res = at.execute("rollback_step", {"chapter": 1, "to_step": "review"}, proj, {})
    assert res["ok"]
    cs = st.get_chapter_step(proj)
    assert cs["step_done"] == "deslop" and cs["votes"] == []   # 审校重跑：票清空


def test_rollback_draft_archives_draft_file(tmp_path):
    proj = _mk_proj(tmp_path)
    draft = project.chapter_draft_path(proj, 1)
    os.makedirs(os.path.dirname(draft), exist_ok=True)
    with open(draft, "w", encoding="utf-8") as f:
        f.write("草稿")
    res = at.execute("rollback_step", {"chapter": 1, "to_step": "draft"}, proj, {})
    assert res["ok"]
    assert not os.path.isfile(draft)                            # 草稿文件已删
    assert st.get_chapter_step(proj).get("step_done", "") in ("", None)   # 断点清空
    # 归档可恢复
    rolls = os.path.join(proj, "pipeline_debug", "agent_tools")
    assert any("draft" in d for d in os.listdir(rolls))


def test_regen_outline_archives_and_removes(tmp_path):
    proj = _mk_proj(tmp_path)
    res = at.execute("regen_outline", {"chapter": 1}, proj, {})
    assert res["ok"]
    assert not os.path.isfile(project.get_outline_path(proj, 1))
    assert any("outline" in d for d in os.listdir(os.path.join(proj, "pipeline_debug", "agent_tools")))


def test_rewrite_chapter_archives_and_carries_guidance(tmp_path):
    proj = _mk_proj(tmp_path)
    res = at.execute("rewrite_chapter", {"chapter": 1, "guidance": "铺垫再足一点"}, proj, {})
    assert res["ok"]
    chapters = {n: p for n, _t, p in project.list_chapters(proj)}
    assert 1 not in chapters   # 正文已清除
    from app import project as pj
    assert "铺垫再足一点" in pj.read_file(os.path.join(proj, "追踪", "阶段指导.md"))


def test_set_setting_whitelist(tmp_path, monkeypatch):
    proj = _mk_proj(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    res = at.execute("set_setting", {"key": "连写", "on": True}, proj, {})
    assert res["ok"]
    from app import config as cfg_mod
    assert cfg_mod.load_config()["writing"]["auto_gate"] is True
    # 白名单外拒绝
    res = at.execute("set_setting", {"key": "api_key", "on": True}, proj, {})
    assert not res["ok"]


def test_write_tools_blocked_while_pipeline_running(tmp_path):
    proj = _mk_proj(tmp_path)
    res = at.execute("rollback_step", {"chapter": 1, "to_step": "review"}, proj, {},
                     pipeline_running=True)
    assert not res["ok"] and "停止" in res["message"]
    # readonly 不受限
    assert at.execute("status", {}, proj, {}, pipeline_running=True)["ok"]


def test_rollback_then_microcycle_resumes_from_step(tmp_path):
    """工具改断点 → 微循环真的从该步续跑（与方案 H 断点语义闭环）"""
    proj = _mk_proj(tmp_path)
    import hashlib
    real_fp = hashlib.sha1("核心事件：测试".encode("utf-8")).hexdigest()[:12]  # 与微循环口径一致
    st.save_chapter_step(proj, 1, step_done="review", draft_path="正文/.drafts/第001.md",
                         votes=[{"x": 1}], outline_fp=real_fp)
    os.makedirs(os.path.dirname(project.chapter_draft_path(proj, 1)), exist_ok=True)
    with open(project.chapter_draft_path(proj, 1), "w", encoding="utf-8") as f:
        f.write("# 第1章 测试\n\n" + "正文内容。" * 400)
    res = at.execute("rollback_step", {"chapter": 1, "to_step": "deslop"}, proj, {})
    assert res["ok"]
    assert st.get_chapter_step(proj)["outline_fp"] == real_fp   # 指纹保留，断点不作废

    class _FakeClient:
        def chat_stream(self, prompt, on_chunk=None, phase="", **kw):
            return "# 第1章 测试\n\n" + "正文内容。" * 400

        def chat(self, prompt, **kw):
            return ""

    class _FakeRouter:
        def __init__(self, c):
            self._c = c

        def client(self, slot):
            return self._c

    class _FakeCtx:
        proj = None
        cfg = {"gates": {"review_enabled": False}, "writing": {"chapter_session": False}}
        router = None
        last_prompt = ""
        review_raw = ""
        stopped = False
        _pause = None

        def log(self, level, msg):
            self.logs.append((level, msg))

        def step(self, num, key):
            self.steps.append(key)

        def stream_stage(self, label):
            pass

        def stream_chunk(self, t):
            pass

        def stream_reasoning(self, t):
            pass

        def gate(self, *a, **k):
            return ""

        def consume_gate_idea(self):
            return None

        def checkpoint(self):
            pass

    ctx = _FakeCtx()
    ctx.proj = proj
    ctx.router = _FakeRouter(_FakeClient())
    ctx.logs = []
    ctx.steps = []
    try:
        stages.chapter_microcycle(ctx, 1)
    except Exception:
        pass   # 假客户端下后续阶段可能解析失败——我们只关心「跳过了草稿」
    assert "draft" not in ctx.steps          # 草稿没有重跑（断点在 review→deslop）
    assert "scan" in ctx.steps or "deslop" in ctx.steps   # 从去味链路继续
