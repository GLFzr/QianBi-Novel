# -*- coding: utf-8 -*-
"""共写档手动查验（去AI味/审校）+ 报告消费态防重复派单 回归

覆盖：
- CwProseCheckWorker：deslop 有 finding → 改写 prompt 注入细纲/原文/黑名单；
  干净文本 → 零 LLM 调用、原文返回；review 模式 FINAL_REVIEW_PROMPT 装配。
- _dispatch_cw_rewrite 幂等认领：首次派发消费报告，二次进入拒绝；
  报告被新一轮比对覆盖（ts 失配）→ 放弃派发。
"""
import os

from app.core import co_dialogue, co_writing, state as st
from app.ui import bridge as bmod


def _mk_proj(tmp_path):
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "正文"))
    os.makedirs(os.path.join(proj, "大纲"))
    with open(os.path.join(proj, "大纲", "细纲_第002章.md"), "w", encoding="utf-8") as f:
        f.write("核心事件：乙事件标记物\n故事内容：略。")
    st.save_state(proj, {"current_chapter": 2, "total_chapters": 10})
    return proj


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
    def __init__(self, reply="改写后的正文。"):
        self.c = _FakeClient(reply)

    def client(self, slot):
        return self.c


# ---------- CwProseCheckWorker ----------

def test_deslop_worker_rewrites_with_outline(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, SLOPPY, mode="deslop",
                                       router=_FakeRouter("干净的改写文本。"))
    w.run()
    assert w.changed is True
    assert w.before_counts[0] >= 1          # 扫描出阻断级 finding
    assert w.result_text == "干净的改写文本。"
    assert "乙事件标记物" in w.last_prompt   # 本章细纲注入
    assert SLOPPY in w.last_prompt           # 原文进 prompt


def test_deslop_worker_clean_text_skips_llm(tmp_path):
    proj = _mk_proj(tmp_path)
    r = _FakeRouter()
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, CLEAN, mode="deslop", router=r)
    w.run()
    assert w.changed is False
    assert w.result_text == CLEAN            # 原文返回
    assert r.c.prompts == []                 # 零 LLM 调用


def test_review_worker_prompt_assembly(tmp_path):
    proj = _mk_proj(tmp_path)
    report = "===VERDICT===\nPASS"
    prose = "本章正文样本。" * 20
    w = co_dialogue.CwProseCheckWorker({}, proj, 2, prose, mode="review",
                                       router=_FakeRouter(report))
    w.run()
    assert w.result_text == report
    assert "本章正文样本。" in w.last_prompt  # 工作副本正文进 prompt
    assert "乙事件标记物" in w.last_prompt    # 本章细纲注入


# ---------- 报告消费态：_dispatch_cw_rewrite 幂等守卫 ----------

class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a, **kw):
        self.calls.append(a)


class _DispatchSelf:
    """轻量 self：不构造 QObject，只喂 _dispatch_cw_rewrite 所需属性/方法"""

    def __init__(self, proj):
        self.proj = proj
        self._cw = co_writing.CoWriting(proj)
        self._cw_worker = None               # worker 已释放路径（不触发 QTimer 重试）
        self.toast = _Sig()
        self.cwReportChanged = _Sig()
        self.spawned = []

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)

    def _get_cw_mode(self):
        return "cw"

    def _get_cw_stage_key(self):
        return st.STAGE_CW_PROSE

    def _spawn_cw_dialogue(self, text, stage, focus_chapter=0):
        self.spawned.append((text, focus_chapter))


def _seed_report(proj, ts="08-31 20:00", text="- 结论：需调整（测试）\n- 【改写指令】把开头改紧凑。"):
    state = st.load_state(proj)
    st.ensure_cw(state)["report"] = {"ts": ts, "num": 2, "text": text}
    st.save_state(proj, state)


def test_dispatch_consumed_blocks_second_run(tmp_path):
    proj = _mk_proj(tmp_path)
    _seed_report(proj)
    fs = _DispatchSelf(proj)
    bmod.Bridge._dispatch_cw_rewrite(fs, 2, "把开头改紧凑。", report_ts="08-31 20:00")
    assert len(fs.spawned) == 1
    assert "（主 Agent 派单）" in fs.spawned[0][0]
    rep = st.ensure_cw(st.load_state(proj)).get("report", {})
    assert rep.get("consumed") is True
    # 第二次进入（自动链重入 / 手动重点）→ 拒绝，不再 spawn
    bmod.Bridge._dispatch_cw_rewrite(fs, 2, "把开头改紧凑。", report_ts="08-31 20:00")
    assert len(fs.spawned) == 1
    assert any("已派发过" in str(c) for c in fs.toast.calls)


def test_dispatch_stale_report_aborts(tmp_path):
    proj = _mk_proj(tmp_path)
    _seed_report(proj, ts="08-31 21:00", text="新一轮报告")
    fs = _DispatchSelf(proj)
    # 携带旧 ts 的自动链 → 报告已被覆盖，放弃且不消费新报告
    bmod.Bridge._dispatch_cw_rewrite(fs, 2, "旧指令", report_ts="08-31 20:00")
    assert fs.spawned == []
    rep = st.ensure_cw(st.load_state(proj)).get("report", {})
    assert not rep.get("consumed")
    assert any("覆盖" in str(c) for c in fs.toast.calls)
