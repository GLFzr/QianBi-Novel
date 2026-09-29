# -*- coding: utf-8 -*-
"""软开局（OB-M1）状态迁移全链回归：docs/共写软开局方案_v1.md §6 判据 2/3/4/5 的可测面

覆盖：
- 触发三条件（新建 ∧ 共写档 ∧ 标记未消费）；auto 档零触发（R17：不写 run_mode）；
- 卡片只在其自然舞台出现（s1↔cw_project、s2↔cw_outline∧Agent 已出话、hand↔有锁定章）；
- 退出路径：跳过（转写零示例条目）/ 手改（改过即表态）/ 交还三出口 / 项目关闭；
- 示例提交 [示例] 留痕 + 选题信息来源标注；无 Key 只允许走到卡片为止（零请求）。
"""
import json
import os
import types

import pytest

from app import project
from app.core import co_dialogue, co_writing, state as st, versions
from app.ui import bridge as bmod


# ---------- 工具 ----------

def _mk_proj(root, name="书", mode="cw"):
    proj = os.path.join(str(root), name)
    project.create_project(str(root), name)
    s = st.load_state(proj)
    st.ensure_cw(s)["mode"] = mode
    st.save_state(proj, s)
    return proj


def _arm(proj):
    s = st.load_state(proj)
    assert co_writing.CoWriting(proj).soft_arm(s)
    st.save_state(proj, s)


class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


class _Recorder:
    """构造即失败——被断言「零请求」的路径上出现任何 worker/客户端实例化即红"""

    def __init__(self, *a, **kw):
        raise AssertionError("该路径不应构造 LLM worker/客户端（零网络请求）")


class _SoftSelf:
    """软开局各槽的轻量 self（不起 Qt 实例；真实方法按需绑定）"""

    def __init__(self, proj, cfg=None, demo_active=False):
        self.proj = str(proj)
        self._cw = co_writing.CoWriting(self.proj)
        self.cfg = cfg if cfg is not None else {"connections": [], "slots": {}}
        self._demo = types.SimpleNamespace(active=demo_active)
        self.toast = _Sig()
        self.cwSoftChanged = _Sig()
        self.cwStageChanged = _Sig()
        self.cwModeChanged = _Sig()
        self.cwStreamingChanged = _Sig()
        self._cw_view = st.STAGE_CW_PROJECT
        self._cur_num = 0
        self._chapter_text = ""
        self._chapter_path = ""
        self._chapter_findings = []
        self.opened = []
        self.chapter_text_emits = 0
        self.locked_emits = 0
        self._pending_rollback = ""
        self._cw_sync_messages = lambda: None
        self._refresh_progress = lambda: None
        self._reset_editor_state = lambda: None
        self._maybe_auto_backup = lambda: None
        self._auto_backup_on_close_book = lambda path: None
        self._remember_session_project = lambda path: None
        for nm in ("lastRecordChanged", "bookTitleChanged", "bookMetaChanged",
                   "hasProjectChanged", "chapterTextChanged", "chapterFindingsChanged",
                   "recoverableDraftChanged", "forcedLocksChanged", "generalChanged",
                   "projectOpened", "cwLockedChanged"):
            setattr(self, nm, _Sig())

    # 真实方法绑定（与被测槽同源，防替身漂移）
    _get_cw_mode = bmod.Bridge._get_cw_mode
    _get_cw_soft = bmod.Bridge._get_cw_soft
    _get_cw_stage_key = bmod.Bridge._get_cw_stage_key
    _slot_readiness = bmod.Bridge._slot_readiness
    _cw_save_state = bmod.Bridge._cw_save_state
    _cw_refresh = bmod.Bridge._cw_refresh
    _cw_soft_submit = bmod.Bridge._cw_soft_submit
    _rollback_to = bmod.Bridge._rollback_to

    def _cw_open_product(self, stage):
        self.opened.append(stage)

    def _refresh_backflow_stale(self):
        pass

    def refreshQueue(self):
        pass

    def openChapter(self, num):
        self._cur_num = num


def _toasts(fs, level=None):
    out = [str(c[1] if len(c) > 1 else c[0]) for c in fs.toast.calls]
    if level:
        out = [str(c[1]) for c in fs.toast.calls if c and c[0] == level]
    return " | ".join(out)


# ---------- 纯状态机（co_writing）----------

def test_arm_cw_only_and_r17_mode_untouched(tmp_path):
    """触发条件②：只有共写档新项目武装；auto 项目零触发且档位不被改写（R17）"""
    proj_cw = _mk_proj(tmp_path, "cw书", mode="cw")
    s = st.load_state(proj_cw)
    assert co_writing.CoWriting(proj_cw).soft_arm(s) is True
    assert s["cw"]["soft"] == co_writing.SOFT_STEP1
    assert s["cw"]["mode"] == "cw"

    proj_auto = _mk_proj(tmp_path, "auto书", mode="auto")
    s2 = st.load_state(proj_auto)
    cw = co_writing.CoWriting(proj_auto)
    assert cw.soft_arm(s2) is False
    assert not s2["cw"].get("soft")
    assert s2["cw"]["mode"] == "auto"          # R17：绝不静默改档
    assert cw.soft_card_step(s2) == ""         # auto 项目永远零卡片


def test_old_project_without_soft_key_is_off(tmp_path):
    """旧项目无 soft 键 = SOFT_OFF：升级后行为与本版本逐字节一致（方案 §6-2 回归面=0）"""
    proj = _mk_proj(tmp_path, "旧书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    assert cw.soft_state(s) == co_writing.SOFT_OFF
    assert cw.soft_card_step(s) == ""
    # 未武装的老项目即使处于任意阶段也不出卡
    st.ensure_cw(s)["stage"] = st.STAGE_CW_PROSE
    assert cw.soft_card_step(s) == ""


def test_arm_no_rearm_after_consume(tmp_path):
    """触发条件③：标记已消费即不再触发（方案 §5 不对存量补投）"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    cw.soft_arm(s)
    cw.soft_consume(s)
    st.save_state(proj, s)
    assert cw.soft_arm(st.load_state(proj)) is False


def test_card_s1_only_at_project_stage(tmp_path):
    """s1 卡只出现在创建项目阶段；阶段走了卡片不跟（但子态仍在，打回即回）"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    cw.soft_arm(s)
    assert cw.soft_card_step(s) == co_writing.SOFT_STEP1
    s["cw"]["stage"] = st.STAGE_CW_CORE
    assert cw.soft_card_step(s) == ""           # 阶段不匹配 → 零卡片（零死路）
    s["cw"]["stage"] = st.STAGE_CW_PROJECT
    assert cw.soft_card_step(s) == co_writing.SOFT_STEP1


def test_card_s2_requires_outline_stage_and_agent_draft(tmp_path):
    """s2 卡双门槛：剧情总纲阶段 ∧ Agent 已出过话（草案/回复在场）"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    s["cw"]["soft"] = co_writing.SOFT_STEP2
    s["cw"]["stage"] = st.STAGE_CW_OUTLINE
    assert cw.soft_card_step(s) == ""                    # 还没出草案
    co_dialogue.transcript_append(s, st.STAGE_CW_OUTLINE, "user", "（生成草案）出总纲")
    assert cw.soft_card_step(s) == ""                    # 只有作者输入也不出
    co_dialogue.transcript_append(s, st.STAGE_CW_OUTLINE, "agent", "（草案）全书三卷…")
    assert cw.soft_card_step(s) == co_writing.SOFT_STEP2
    s["cw"]["stage"] = st.STAGE_CW_WORLDBOOK
    assert cw.soft_card_step(s) == ""                    # 过了这一阶段即退场


def test_card_hand_requires_locked_chapter(tmp_path):
    """hand 卡门槛：存在已锁定章（第一章交还评判的触发点）"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    s["cw"]["soft"] = co_writing.SOFT_HANDOFF
    s["cw"]["stage"] = st.STAGE_CW_PROSE
    assert cw.soft_card_step(s) == ""
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    with open(os.path.join(proj, "正文", "第0001章.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 开端\n正文。")
    project.set_chapter_locked(proj, 1, True)
    assert cw.soft_card_step(s) == co_writing.SOFT_HANDOFF


def test_consume_only_active_is_idempotent(tmp_path):
    """消费只对活动态生效；done/off 反复消费不漂移"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    assert cw.soft_consume(s, only_active=True) == ""          # 未武装：不动
    cw.soft_arm(s)
    assert cw.soft_consume(s, only_active=True) == co_writing.SOFT_DONE
    assert cw.soft_consume(s, only_active=True) == co_writing.SOFT_DONE  # 幂等


def test_full_journey_transitions(tmp_path):
    """全链状态迁移：s1 --用示例--> s2 --发送/先不用--> hand --三选一--> done"""
    proj = _mk_proj(tmp_path, "书", mode="cw")
    cw = co_writing.CoWriting(proj)
    s = st.load_state(proj)
    cw.soft_arm(s)
    assert cw.soft_card_step(s) == co_writing.SOFT_STEP1
    cw.soft_consume(s, co_writing.SOFT_STEP2)                  # 「就用这个开写」后
    s["cw"]["stage"] = st.STAGE_CW_OUTLINE
    co_dialogue.transcript_append(s, st.STAGE_CW_OUTLINE, "agent", "草案")
    assert cw.soft_card_step(s) == co_writing.SOFT_STEP2
    cw.soft_consume(s, co_writing.SOFT_HANDOFF)                # 发送/先不用
    s["cw"]["stage"] = st.STAGE_CW_PROSE
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    with open(os.path.join(proj, "正文", "第0001章.md"), "w", encoding="utf-8") as f:
        f.write("正文")
    project.set_chapter_locked(proj, 1, True)
    assert cw.soft_card_step(s) == co_writing.SOFT_HANDOFF
    cw.soft_consume(s, only_active=True)                       # 三出口任一
    assert cw.soft_state(s) == co_writing.SOFT_DONE
    assert cw.soft_card_step(s) == ""                          # 终局零卡片


def test_field_notes_and_example_assets():
    """逐字段旁注四件齐全（key 唯一、注非空）；示例灵感/示范追问本地写死非空"""
    keys = [k for k, _lb, _n in co_writing.SOFT_FIELD_NOTES]
    assert keys == ["genre", "platform", "words", "idea"]
    assert all(lb and n for _k, lb, n in co_writing.SOFT_FIELD_NOTES)
    assert co_writing.SOFT_EXAMPLE_IDEA.strip()
    assert co_writing.SOFT_EXAMPLE_REPLY.strip()


# ---------- bridge 槽（轻量 self 替身）----------

def _armed_self(tmp_path, cfg=None, demo=False, name="书"):
    proj = _mk_proj(tmp_path, name, mode="cw")
    _arm(proj)
    return _SoftSelf(proj, cfg=cfg, demo_active=demo)


def test_use_example_marks_and_advances(tmp_path):
    """「就用这个开写」：真实链提交——[示例] 留痕 + 选题来源标注 + 推进核心设定 + s2"""
    fs = _armed_self(tmp_path)
    fs.cfg = {"connections": [{"id": "c1", "name": "测试", "base_url": "http://127.0.0.1:9",
                               "api_key": "k", "model": "m"}], "slots": {}}
    bmod.Bridge.cwSoftUseExample(fs)
    state = st.load_state(fs.proj)
    cw = st.ensure_cw(state)
    assert cw["soft"] == co_writing.SOFT_STEP2
    assert cw.get("soft_used_example") is True
    assert cw["stage"] == st.STAGE_CW_CORE
    turns = cw["transcript"][st.STAGE_CW_PROJECT]
    assert turns and turns[0]["role"] == "user" and turns[0]["text"].startswith("[示例]")
    doc = open(os.path.join(fs.proj, "设定", "选题信息.md"), encoding="utf-8").read()
    assert "来源：示例开局" in doc
    assert "进入「核心设定」" in _toasts(fs)


def test_use_example_without_key_stops_at_card_zero_request(tmp_path, monkeypatch):
    """红线5：无 Key 只允许走到卡片为止——零请求零计费，子态原地不动"""
    fs = _armed_self(tmp_path)   # cfg 无任何连接
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "SummarizeWorker", _Recorder)
    bmod.Bridge.cwSoftUseExample(fs)
    state = st.load_state(fs.proj)
    cw = st.ensure_cw(state)
    assert cw["soft"] == co_writing.SOFT_STEP1               # 仍停在卡片
    assert cw["stage"] == st.STAGE_CW_PROJECT                # 未推进
    assert not cw.get("transcript", {}).get(st.STAGE_CW_PROJECT)   # 零提交条目
    assert "连接" in _toasts(fs, "warn")                     # 人话缺因（深链）


def test_skip_leaves_no_example_entry(tmp_path):
    """「跳过，我自己说」：软开局终止且转写零示例条目（方案 §6-3 判据）"""
    fs = _armed_self(tmp_path)
    bmod.Bridge.cwSoftSkip(fs)
    state = st.load_state(fs.proj)
    cw = st.ensure_cw(state)
    assert cw["soft"] == co_writing.SOFT_DONE
    assert not cw.get("transcript", {}).get(st.STAGE_CW_PROJECT)
    assert "✓ 确定" in _toasts(fs, "info")


def test_edited_submit_consumes_with_user_voice(tmp_path):
    """「我来改」提交：作者自己的话原样留痕（无 [示例] 前缀）+ 改过即表态（done）"""
    fs = _armed_self(tmp_path)
    bmod.Bridge.cwSoftSubmitEdited(fs, "科幻", "起点", 150, "我自己的点子")
    state = st.load_state(fs.proj)
    cw = st.ensure_cw(state)
    assert cw["soft"] == co_writing.SOFT_DONE
    turns = cw["transcript"][st.STAGE_CW_PROJECT]
    assert turns[0]["text"].startswith("立项确认")
    assert "[示例]" not in turns[0]["text"]
    info = project.read_idea_info(fs.proj)
    assert info["genre"] == "科幻" and info["idea"] == "我自己的点子"


def test_self_confirm_advances_s1_to_s2(tmp_path):
    """作者没走示例卡、自己点「确定」：示例卡退场（s2），示范与交还保留"""
    fs = _armed_self(tmp_path)
    project.write_idea_info(fs.proj, "都市", "番茄", "测试灵感", 100)
    bmod.Bridge._confirm_cw_project(fs)
    cw = st.ensure_cw(st.load_state(fs.proj))
    assert cw["soft"] == co_writing.SOFT_STEP2
    assert cw["stage"] == st.STAGE_CW_CORE


def test_step2_send_and_defer_to_hand(tmp_path, monkeypatch):
    """示范卡：发送走真实讨论链；先不用/改改再发静默退场——两者都到 hand"""
    fs = _armed_self(tmp_path)
    state = st.load_state(fs.proj)
    state["cw"]["soft"] = co_writing.SOFT_STEP2
    state["cw"]["stage"] = st.STAGE_CW_OUTLINE
    co_dialogue.transcript_append(state, st.STAGE_CW_OUTLINE, "agent", "草案")
    st.save_state(fs.proj, state)
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "SummarizeWorker", _Recorder)
    # submitCwMessage 全链太重（agent 指令解析等），此处替身只钉「真实链被调用」
    sent = []
    fs.submitCwMessage = lambda text, mode="discuss": sent.append((text, mode))
    bmod.Bridge.cwSoftStep2Send(fs)
    assert sent and sent[0][0] == co_writing.SOFT_EXAMPLE_REPLY
    assert st.ensure_cw(st.load_state(fs.proj))["soft"] == co_writing.SOFT_HANDOFF

    fs2 = _armed_self(tmp_path, name="书2")
    state = st.load_state(fs2.proj)
    state["cw"]["soft"] = co_writing.SOFT_STEP2
    state["cw"]["stage"] = st.STAGE_CW_OUTLINE
    st.save_state(fs2.proj, state)
    bmod.Bridge.cwSoftStep2Defer(fs2)
    assert st.ensure_cw(st.load_state(fs2.proj))["soft"] == co_writing.SOFT_HANDOFF


def _lock_first_chapter(fs):
    os.makedirs(os.path.join(fs.proj, "正文"), exist_ok=True)
    with open(os.path.join(fs.proj, "正文", "第0001章.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 开端\n" + "正文内容。" * 50)
    project.set_chapter_locked(fs.proj, 1, True)
    state = st.load_state(fs.proj)
    state["cw"]["soft"] = co_writing.SOFT_HANDOFF
    state["cw"]["stage"] = st.STAGE_CW_PROSE
    state["history"] = [{"num": 1, "title": "开端", "words": 1500}]
    st.save_state(fs.proj, state)


def test_hand_card_payload_growth_lines(tmp_path):
    """交还卡「怎么长出来的」：数据全部来自既有落盘，零新增埋点"""
    fs = _armed_self(tmp_path)
    _lock_first_chapter(fs)
    state = st.load_state(fs.proj)
    cw = st.ensure_cw(state)
    cw["soft_used_example"] = True
    cw["supervised"] = {"1": "09-29 10:00"}
    st.save_review_findings(fs.proj, state, 1, "PASS", [], [], [])
    st.save_state(fs.proj, state)
    card = fs._get_cw_soft()
    assert card["step"] == co_writing.SOFT_HANDOFF
    assert card["chapter"] == 1
    assert any("示例开局" in g for g in card["growth"])
    assert any("衔接比对" in g for g in card["growth"])
    assert any("审校" in g for g in card["growth"])
    assert card["exportHint"]


def test_hand_continue_and_edit_exits(tmp_path):
    """交还三出口之「继续共写」「我来改」：都消费软开局；我来改解锁本章"""
    fs = _armed_self(tmp_path)
    _lock_first_chapter(fs)
    bmod.Bridge.cwSoftHandContinue(fs)
    assert st.ensure_cw(st.load_state(fs.proj))["soft"] == co_writing.SOFT_DONE
    assert project.is_chapter_locked(fs.proj, 1)             # 继续共写：锁定原样

    fs2 = _armed_self(tmp_path, name="书2")
    _lock_first_chapter(fs2)
    bmod.Bridge.cwSoftHandEdit(fs2)
    state = st.load_state(fs2.proj)
    assert st.ensure_cw(state)["soft"] == co_writing.SOFT_DONE
    assert not project.is_chapter_locked(fs2.proj, 1)        # 我来改：已解锁进编辑器
    assert fs2._cur_num == 1
    assert "解锁" in _toasts(fs2, "ok")


def test_hand_restart_archives_and_rolls_back(tmp_path):
    """交还三出口之「换个方向重来」：本章归档清除 + 打回核心设定 + 不再代填"""
    fs = _armed_self(tmp_path)
    _lock_first_chapter(fs)
    # 下游产物（大纲/世界书）供级联归档断言
    project.write_file(os.path.join(fs.proj, "大纲", "大纲.md"), "# 大纲")
    project.write_file(os.path.join(fs.proj, "设定", "世界书.md"), "# 世界书")
    bmod.Bridge.cwSoftHandRestart(fs)
    state = st.load_state(fs.proj)
    assert st.ensure_cw(state)["soft"] == co_writing.SOFT_DONE
    assert st.ensure_cw(state)["stage"] == st.STAGE_CW_CORE
    assert not project.is_chapter_locked(fs.proj, 1)
    chapters = [n for n, _t, _p in project.list_chapters(fs.proj)]
    assert 1 not in chapters                                  # 本章已归档清除
    assert not os.path.isfile(os.path.join(fs.proj, "大纲", "大纲.md"))
    # 先归档再删除：版本历史里有换向归档底
    assert any("软开局换向归档" == v.get("source")
               for v in versions.list_versions(fs.proj, 1))


def test_demo_active_blocks_soft_slots(tmp_path):
    """演示硬隔离互斥：演示中软开局三个提交口一律不接管（红线3）"""
    fs = _armed_self(tmp_path, demo=True)
    bmod.Bridge.cwSoftUseExample(fs)
    bmod.Bridge.cwSoftSubmitEdited(fs, "科幻", "番茄", 100, "点子")
    assert st.ensure_cw(st.load_state(fs.proj))["soft"] == co_writing.SOFT_STEP1
    assert st.ensure_cw(st.load_state(fs.proj))["stage"] == st.STAGE_CW_PROJECT


def test_new_project_arms_soft_start(tmp_path, monkeypatch):
    """触发条件①②③：newProject 落武装（共写档）；演示中不武装"""

    class _NewProjSelf:
        _get_cw_mode = bmod.Bridge._get_cw_mode

        def __init__(self, demo=False):
            self._demo = types.SimpleNamespace(active=demo)
            self.cfg = {"writing": {"run_mode": "cw"}, "general": {}}
            self.toast = _Sig()
            self.cwSoftChanged = _Sig()
            self.opened = []
            self.proj = None   # 工厂档位解析路径（_get_cw_mode 无项目分支）

        def _open_project(self, path, silent=False):
            self.opened.append(path)

    fs = _NewProjSelf()
    root = str(tmp_path / "books")
    os.makedirs(root, exist_ok=True)
    assert bmod.Bridge.newProject(fs, root, "新书", "都市", "番茄", 100, "灵感", "") is True
    state = st.load_state(os.path.join(root, "新书"))
    assert st.ensure_cw(state)["soft"] == co_writing.SOFT_STEP1
    assert st.ensure_cw(state)["mode"] == "cw"

    # 演示中建书不武装
    fs2 = _NewProjSelf(demo=True)
    assert bmod.Bridge.newProject(fs2, root, "演示书", "都市", "番茄", 100, "灵感", "") is True
    state = st.load_state(os.path.join(root, "演示书"))
    assert not st.ensure_cw(state).get("soft")


def test_open_project_consumes_active_soft(tmp_path, monkeypatch):
    """第四退出「项目关闭」：换书打开旧项目时在途子态消费（重启后不复活）"""
    proj = _mk_proj(tmp_path / "a", "书", mode="cw")
    _arm(proj)
    other = _mk_proj(tmp_path / "b", "他书", mode="cw")
    # 目标项目带着在途子态（模拟上次会话中途退出）
    s = st.load_state(other)
    s["cw"]["soft"] = co_writing.SOFT_STEP2
    st.save_state(other, s)

    import app.dialogue_log as dlg
    monkeypatch.setattr(dlg, "configure", lambda *a, **k: None)
    monkeypatch.setattr(bmod.cfg_mod, "push_recent_project", lambda cfg, path: None)
    monkeypatch.setattr(bmod.cfg_mod, "save_config", lambda cfg: None)
    fs = _SoftSelf(proj)
    bmod.Bridge._open_project(fs, other)
    assert st.ensure_cw(st.load_state(other))["soft"] == co_writing.SOFT_DONE
