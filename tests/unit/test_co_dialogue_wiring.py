# -*- coding: utf-8 -*-
"""S2d 消费接线回归：co_dialogue × state_card（卡9-P2）× deslop_metrics（卡6S）

- 状态卡注入开关：prose 参考块尾部追加【续写状态卡】；关位逐字回退旧装配
  （开位输出以关位输出为严格前缀，差集恰为注入的卡块=字节对照）；
  非 prose 阶段开/关逐字相同（注入口只在 prose 分支）。
- 预算行为：注入的卡受 STATE_CARD_BUDGET 约束（裁剪逻辑在 state_card 内置：
  低优先级栏整项让位，P0 当前位置/下一章承诺永不丢）。
- 卡6S：CwProseCheckWorker deslop 改写前后各调 compute_metrics，完整指标
  进对比记录（before_metrics/after_metrics；after 的 guard 组由 compute_guard
  回填）；零改动路径同样留对照记录。
全部 tmp_path 真实文件 + 假路由，纯本地零 API。
"""
import os

import pytest

from app.core import co_dialogue, state as st


def _mk_proj(tmp_path):
    """ch1/ch2 存在 + 细纲齐备（参考块与状态卡都有真实数据可吃）"""
    proj = str(tmp_path)
    for d in ("正文", "大纲", "设定"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    with open(os.path.join(proj, "正文", "第001章_甲.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 甲\n" + "第一章内容铺垫。" * 40 + "第一章结尾钩子。")
    with open(os.path.join(proj, "正文", "第002章_乙.md"), "w", encoding="utf-8") as f:
        f.write("# 第2章 乙\n" + "第二章内容承接。" * 40)
    for n, ev in [(1, "甲事件"), (2, "乙事件")]:
        with open(os.path.join(proj, "大纲", f"细纲_第{n:03d}章.md"), "w", encoding="utf-8") as f:
            f.write(f"- 核心事件：{ev}\n- 故事内容：略。\n")
    st.save_state(proj, {"current_chapter": 2, "total_chapters": 10})
    return proj


# ---------- 卡9-P2：状态卡注入开关 ----------

def test_state_card_on_off_byte_compare(tmp_path):
    """开关 off = 逐字回退旧装配：off 输出是 on 输出的严格前缀，差集恰为卡块"""
    proj = _mk_proj(tmp_path)
    ref_on = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "", focus_chapter=2)
    assert "【续写状态卡】" in ref_on
    assert "## 当前位置" in ref_on                     # P0 栏在场
    co_dialogue.STATE_CARD_ENABLED = False
    try:
        ref_off = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "",
                                                      focus_chapter=2)
    finally:
        co_dialogue.STATE_CARD_ENABLED = True
    assert "【续写状态卡】" not in ref_off
    # 字节对照：关位=旧装配逐字不变；开位只是在尾部追加了卡块
    assert ref_on.startswith(ref_off)
    suffix = ref_on[len(ref_off):]
    assert suffix.startswith("\n\n【续写状态卡】\n")
    assert "## 近三章速记(读者已知)" not in ref_off    # 旧装配里没有七栏卡结构


def test_state_card_switch_never_touches_non_prose(tmp_path):
    """注入口只在 prose 分支：非 prose 阶段开/关逐字相同"""
    proj = _mk_proj(tmp_path)
    ref_on = co_dialogue.compose_reference_block(proj, st.STAGE_CW_CORE, "")
    saved = co_dialogue.STATE_CARD_ENABLED
    co_dialogue.STATE_CARD_ENABLED = False
    try:
        ref_off = co_dialogue.compose_reference_block(proj, st.STAGE_CW_CORE, "")
    finally:
        co_dialogue.STATE_CARD_ENABLED = saved
    assert ref_on == ref_off
    assert "【续写状态卡】" not in ref_on


def test_dialogue_worker_prompt_carries_state_card(tmp_path):
    """端到端：DialogueWorker 组装的真机 prompt 带上状态卡"""
    proj = _mk_proj(tmp_path)

    class _FakeRouter:
        def client(self, slot):
            class _C:
                def chat_stream(self, prompt, on_chunk=None, **kw):
                    return "好的。"

            return _C()

    w = co_dialogue.DialogueWorker({}, proj, st.STAGE_CW_PROSE, "继续", router=_FakeRouter(),
                                   focus_chapter=2)
    w.run()
    assert "【续写状态卡】" in w.last_prompt
    assert w.result_text == "好的。"


# ---------- 卡9-P2：compose_reference_block 预算行为 ----------

def test_compose_reference_block_trims_card_to_budget(tmp_path, monkeypatch):
    """追踪涨满后注入的卡仍 ≤ 预算：低优先级栏整栏让位，P0 永不丢（裁剪在 state_card 内置）"""
    from app.core import tracking_store
    proj = _mk_proj(tmp_path)
    long_desc = "身份层层嵌套；" + "线索盘根错节，" * 30          # ≈217 字/角色
    tracking_store.apply_character_updates(
        proj, 1, [], [],
        new_chars=[{"id": "角色%02d" % i, "当前身份": long_desc, "当前能力": long_desc,
                    "record": "登场"} for i in range(8)])
    with open(os.path.join(proj, "设定", "正则.md"), "w", encoding="utf-8") as f:
        for i in range(12):
            f.write("- 规则：本书硬性禁则第%d条，不得出现现代物件与网络用语%d号"
                    "｜level: must｜scope: 全书\n" % (i, i))
    monkeypatch.setattr(co_dialogue, "STATE_CARD_BUDGET", 1200)
    ref = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "", focus_chapter=2)
    assert "【续写状态卡】" in ref
    card = ref.split("【续写状态卡】\n", 1)[1]        # 注入在参考块末尾
    assert len(card.encode("utf-8")) <= co_dialogue.STATE_CARD_BUDGET
    assert "## 当前位置" in card                       # P0 永不丢
    assert "## 下一章承诺" in card                     # P0 永不丢
    assert "## 长期约束(正则must)" not in card         # P4 整栏让位（整项取舍不截半句）
    # 参考块既有的手工切片不受状态卡预算影响（防两套截断哲学互相污染）
    assert "【本章细纲】" in ref and "乙事件" in ref


# ---------- 卡6S：metrics 进 before/after 对比记录 ----------

SLOPPY = "他不知道的是，这一切才刚刚开始。他仿佛看到了命运的齿轮。"
CLEAN = "夜里落了雨。陈更坐在门口，把账算了一遍。天亮前他又去看了眼仓库。"


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat_stream(self, prompt, on_chunk=None, **kw):
        self.prompts.append(prompt)
        return self.reply

    def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.reply


class _FakeRouter:
    def __init__(self, reply="干净的改写文本。"):
        self.c = _FakeClient(reply)

    def client(self, slot):
        return self.c


def test_deslop_metrics_in_before_after_records(tmp_path):
    """改写前后各算完整指标：before/after 记录扩出 metrics 字段，guard 组回填对照"""
    proj = _mk_proj(tmp_path)
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, SLOPPY, mode="deslop",
                                       router=_FakeRouter("干净的改写文本。"))
    w.run()
    assert w.changed is True
    for rec in (w.before_metrics, w.after_metrics):
        assert {"aid", "chars", "by_rule", "rhythm", "connectivity", "special"} <= set(rec)
    assert w.before_counts[0] >= 1                     # 旧字段（扫描计数）仍在
    assert w.before_metrics["aid"] > 0                 # 改前确实扫出特征
    assert w.before_metrics["by_rule"], "改前分规则命中表非空"
    # 改后干净稿：AID 归零；guard 组记录改前↔改后对照
    assert w.after_metrics["aid"] == 0
    assert w.before_metrics["aid"] > w.after_metrics["aid"]
    guard = w.after_metrics["guard"]
    assert guard["chars_kept_ratio"] is not None and 0 < guard["chars_kept_ratio"] <= 1
    assert guard["para_delta"] == 0                    # 单段↔单段
    assert guard["new_must_violations"] is None        # 卡7 出口，本卡不填


def test_deslop_clean_text_records_identity_metrics(tmp_path):
    """零改动路径（无 finding 短路）同样留对照记录：前后同文，guard=原样保持"""
    proj = _mk_proj(tmp_path)
    r = _FakeRouter()
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, CLEAN, mode="deslop", router=r)
    w.run()
    assert w.changed is False
    assert r.c.prompts == []                           # 零 LLM 调用（旧行为不变）
    assert w.before_metrics["aid"] == 0.0
    assert w.after_metrics["chars"] == w.before_metrics["chars"]
    guard = w.after_metrics["guard"]
    assert guard["chars_kept_ratio"] == 1.0 and guard["para_delta"] == 0


@pytest.mark.parametrize("mode", ["deslop", "review"])
def test_metrics_only_on_deslop_mode(tmp_path, mode):
    """review 模式不产指标（报告文本走 bridge 解析），deslop 模式必产——互不串档"""
    proj = _mk_proj(tmp_path)
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, SLOPPY, mode=mode,
                                       router=_FakeRouter("===VERDICT===\nPASS"
                                                          if mode == "review"
                                                          else "干净的改写文本。"))
    w.run()
    if mode == "deslop":
        assert w.before_metrics is not None and w.after_metrics is not None
    else:
        assert w.before_metrics is None and w.after_metrics is None
