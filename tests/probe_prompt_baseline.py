# -*- coding: utf-8 -*-
"""W0a 提示词装配基线探针（回归护栏）

目的：本方案要重构世界书装配（wb.py）与 LLM payload 构造（_build_payload），
这些改动**理应不改变**送进模型的字节。本探针用固定夹具书 + mock LLM 跑一遍
全部装配点，把每次 LLM 调用收到的 prompt 逐条 sha256 落基线，之后任何改动
只跑这一个脚本就能看出「哪一处装配变了」。

纪律：
- W0b/W0c/P0a（纯重构）必须 **0 漂移**；
- W2 起允许的有意漂移，用 `--update-baseline` 刷新并在提交说明里逐条写明原因。

用法：
  .venv/Scripts/python.exe tests/probe_prompt_baseline.py                 # 比对（漂移即非零退出）
  .venv/Scripts/python.exe tests/probe_prompt_baseline.py --update-baseline   # 刷新基线
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_pb_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import probe_guard  # noqa: E402

probe_guard.arm_config_guard()

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])

from app import config as cfg_mod  # noqa: E402
from app import project, prompts  # noqa: E402
from app.core import orchestrator as orch_mod  # noqa: E402
from app.core import state as st  # noqa: E402

BASELINE = os.path.join(_ROOT, "tests", "evals", "prompt_baseline.json")

# ---------------- 夹具内容（全部固定字符串，保证可复现） ----------------

BOOK = "探针书"
GENRE = "都市悬疑"
PRESET = "urban_destiny"      # v2 内置预设：六个 stage_hints 与六个共享字段全填
IDEA = "主角的笔记本能改写已经发生的事，代价是忘掉等价的日子。"

WB_FIXTURE = """# 世界书

## 实体登记

### 陈更
- 身份：当铺学徒，逆命者
- 约束：不能说出自己改写过的日期
- 声口：短句，从不解释

### 柳三更
- 身份：当铺掌柜之女
- 约束：只信账本不信人

## 规则与数值基准

- 改写一次代价 = 忘掉 3 天；余额低于 1 天不可再改写
- 当铺子时清账，清账时所有人不能说谎

## 附录·旧档

（本节为陈旧条目，用于测试预算与激活优先级）
"""

WB_ADDITIONAL = """
## 追加登记

- **第九指**（道具）：可替持有者承担一次改写代价 ｜ 首见第2章
- **清账规则**（规则）：子时清账时不能说谎，违者当日记忆归零 ｜ 首见第2章
"""

RG_FIXTURE = """# 正则约束

- 规则：不得出现「仿佛」「似乎」等推测性比喻｜level：must｜scope：prose
- 规则：每章至少一处具体价钱或数字，且不重复使用同一金额
  续行示例：灵石、时薪、当票面额均可。
"""

MOCK_CORE = """# 核心设定
- 题材：都市悬疑
- 主角：陈更
- 金手指：改写账本
- 主要角色表
- 陈更：当铺学徒
- 柳三更：掌柜之女
"""

MOCK_VOLUME = """# 大纲
### 第1卷 清账（第1-10章）
- 卷契约：陈更用第一次改写换来父亲的清白
"""

MOCK_WORLDBOOK = "# 世界书\n\n（首版占位，随后被夹具覆盖）\n"


def _mock_outline(n: int) -> str:
    return (f"### 第{n}章 第{n}章章名\n"
            f"- 章名：第{n}章章名\n"
            f"- 核心事件：陈更在第{n}次清账夜改写当票\n"
            f"- 出场顺序：陈更、柳三更\n"
            f"- 承接锚点：上一章结尾\n"
            f"- 故事内容：陈更典当三日记忆，柳三更查账发现缺口\n"
            f"- 金手指使用：{'有' if n % 2 else '无'}\n"
            f"- 资源收支：余额 -3 天\n"
            f"- 字数：3000\n"
            f"- 章末钩子：当票上多出第三个指印\n")


def _mock_prose(n: int, mult: int = 29) -> str:
    para = (f"第{n}章正文样本。陈更把当票压在柜台上，柳三更没有抬头。"
            f"子时的灯灭了三次，账本上多出一行不属于任何人的字。"
            f"他想起父亲说过，清账的时候不能说谎。"
            "余下的段落用于凑够目标字数，内容保持固定以保证本探针可复现。") * mult
    return f"# 第{n}章 第{n}章章名\n\n" + para


MOCK_REVIEW_PASS = """===A_GOLDEN_OPEN=== pass 开篇有力 【原文引证：陈更把当票压在柜台上】
===B_PAYOFF=== pass 爽点到位
===C_FINGER=== pass 金手指未越界
===D_PLOT=== pass 因果链完整
===E_CHARACTER=== pass 声口未崩
===F_HOOK=== pass 钩子成立
===VERDICT===
PASS
===END===
"""

# 引证必须逐字存在于 _mock_prose，否则会被 P1 验真降级（那就测不到修复环了）
MOCK_REVIEW_R2 = """===A_GOLDEN_OPEN=== pass 开篇有力
===B_PAYOFF=== marginal 爽点略迟
===C_FINGER=== pass 金手指未越界
===D_PLOT=== fail 清账夜规则未铺垫就生效 【原文引证：他想起父亲说过，清账的时候不能说谎】 → root: ROOT_OUTLINE
===E_CHARACTER=== pass 声口未崩
===F_HOOK=== fail 钩子与前章同构 【原文引证：子时的灯灭了三次】 → root: ROOT_PROSE
===VERDICT===
REJECT
===END===
"""

MOCK_REVIEW_R1 = """===A_GOLDEN_OPEN=== pass 开篇有力
===B_PAYOFF=== pass 爽点到位
===C_FINGER=== pass 金手指未越界
===D_PLOT=== fail 清账夜规则仍未回收 【原文引证：他想起父亲说过，清账的时候不能说谎】 → root: ROOT_OUTLINE
===E_CHARACTER=== pass 声口未崩
===F_HOOK=== pass 钩子成立
===VERDICT===
REJECT
===END===
"""

# 审校回复序列：第 1 章 PASS；第 2 章 R2 → R1 → PASS（触发修复环 + 根因溯源）；之后恒 PASS
_REVIEW_SEQ = [MOCK_REVIEW_PASS, MOCK_REVIEW_R2, MOCK_REVIEW_R1, MOCK_REVIEW_PASS]

MOCK_TRACKING = """===角色状态===
陈更：余额 -3 天，右手食指发黑
柳三更：已查到账目缺口
===伏笔===
新增：第三枚指印｜未回收
===时间线===
第{n}章：清账夜
===上下文===
陈更开始怀疑当票会自己多出来。
===新实体===
===新规则===
===实体演进===
===世界观揭示===
===一句话摘要===
陈更典当三日记忆，柳三更查账发现缺口。
"""

MOCK_BACKFLOW = """===新实体===
第九指｜道具｜可替持有者承担一次改写代价
===新规则===
清账规则｜子时清账时不能说谎，违者当日记忆归零
===伏笔变动===
新增：第三枚指印
回收：无
===实体演进===
陈更｜余额｜0→-3 天
===世界观揭示===
当铺｜清账夜的灯会自己灭三次
===偏离点===
无
===一句话摘要===
陈更典当三日记忆换来父亲清白。
"""

MOCK_SUMMARY = "第{n}章：陈更典当三日记忆，柳三更查账发现缺口。"
MOCK_GLOBAL = "全书主线：陈更以记忆为代价改写账本，柳三更逐章逼近真相。"
MOCK_BLURB = "标签：都市悬疑 / 金手指 / 双主角\n简介：一本能改写过去的账本，代价是忘掉等价的日子。"
MOCK_DIALOGUE = "明白。这一段我会保持短句、不解释的声口，并把清账夜的灯写准。"


# ---------------- mock LLM：按模板字面片段签名分派固定回复 + 记录 prompt ----------------

_SIGS = {}


def _sig_of(tmpl: str) -> tuple:
    """模板 → 字面片段签名（跳过 {占位符}，取前 3 个足够长的片段）"""
    frags = []
    for frag in re.split(r"\{[^{}]*\}", tmpl or ""):
        f = frag.strip()
        if len(f) >= 16:
            frags.append(f[:60])
        if len(frags) == 3:
            break
    if not frags:
        raise AssertionError("模板没有可用作签名的字面片段")
    return tuple(frags)


def _reg(kind: str, tmpl: str):
    sig = _sig_of(tmpl)
    for other, osig in _SIGS.items():
        if osig == sig:
            raise AssertionError(f"签名冲突：{kind} 与 {other} 的字面片段完全相同")
    _SIGS[kind] = sig


for _kind, _name in [
    ("core", "CORE_SETTING_PROMPT"), ("volume", "VOLUME_OUTLINE_PROMPT"),
    ("worldbook_gen", "WORLDBOOK_GEN_PROMPT"), ("outline", "CHAPTER_OUTLINE_PROMPT"),
    ("prose", "PROSE_WRITING_PROMPT"),
    ("co_outline", "CO_OUTLINE_REVIEW_PROMPT"), ("co_readback", "CO_READBACK_PROMPT"),
    ("co_summarize", "CO_SUMMARIZE_PROMPT"), ("co_supervisor", "CO_SUPERVISOR_PROMPT"),
    ("co_unit", "CO_UNIT_OUTLINE_PROMPT"),
    ("dialogue", "CO_DIALOGUE_PROMPT"), ("review", "FINAL_REVIEW_PROMPT"),
    ("root_cause", "ROOT_CAUSE_PROMPT"), ("review_fix", "REVIEW_FIX_PROMPT"),
    ("review_v1", "REVIEW_PROMPT"), ("tracking", "TRACKING_UPDATE_PROMPT"),
    ("backflow", "MEMORY_BACKFLOW_PROMPT"), ("chapter_summary", "CHAPTER_SUMMARY_PROMPT"),
    ("global_summary", "GLOBAL_SUMMARY_PROMPT"), ("blurb", "BLURB_AND_TAGS_PROMPT"),
    ("enrich", "ENRICH_PROMPT"), ("trim", "TRIM_PROMPT"),
    ("deslop", "DESLOP_REWRITE_PROMPT"), ("selection", "SELECTION_REWRITE_PROMPT"),
    ("revision", "REVISION_TARGETS_PROMPT"), ("idea", "IDEA_EXPAND_PROMPT"),
]:
    _reg(_kind, getattr(prompts, _name))

_CH_NUM = re.compile(r"第\s*(\d+)\s*章")


class Recorder:
    """记录每次 LLM 调用（kind/slot/prompt），并返回固定回复"""

    def __init__(self):
        self.calls = []      # [(kind, slot, prompt)]
        self._chapter = [1]  # 当前章号（夹具按章模板化）
        self._review_step = 0  # 审校第几次被调（用于走 REJECT→修复→根因→PASS 环）
        self.prose_mult = 29   # 正文重复段数：29≈2930 字，落在字数闸门容差内

    def kind(self, prompt: str) -> str:
        hits = [(sum(len(f) for f in sig), k)
                for k, sig in _SIGS.items() if all(f in prompt for f in sig)]
        if not hits:
            return "unknown"
        hits.sort(reverse=True)
        if len(hits) > 1 and hits[0][0] == hits[1][0]:
            raise AssertionError(f"prompt 同时命中两类装配且无法区分：{hits[:2]}")
        return hits[0][1]

    def reply(self, kind: str, prompt: str) -> str:
        m = _CH_NUM.search(prompt)
        n = int(m.group(1)) if m else self._chapter[0]
        if kind == "core":
            return MOCK_CORE
        if kind == "volume":
            return MOCK_VOLUME
        if kind == "worldbook_gen":
            return MOCK_WORLDBOOK
        if kind in ("outline", "co_unit"):
            nums = [int(x) for x in _CH_NUM.findall(prompt)]
            lo = min(nums) if nums else n
            return "\n\n".join(_mock_outline(k) for k in range(lo, min(lo + 4, lo + 6)))
        if kind in ("prose", "enrich", "trim", "unknown", "selection", "revision"):
            return self._prose(n)
        if kind == "deslop":
            return self._prose(n)
        if kind == "review":
            step = self._review_step
            self._review_step += 1
            return _REVIEW_SEQ[step] if step < len(_REVIEW_SEQ) else MOCK_REVIEW_PASS
        if kind == "review_v1":
            return "===VERDICT===\nPASS\n"
        if kind == "root_cause":
            return "（无上游根因）"
        if kind == "review_fix":
            return self._prose(n)
        if kind == "tracking":
            return MOCK_TRACKING.format(n=n)
        if kind == "backflow":
            return MOCK_BACKFLOW
        if kind == "chapter_summary":
            return MOCK_SUMMARY.format(n=n)
        if kind == "global_summary":
            return MOCK_GLOBAL
        if kind == "blurb":
            return MOCK_BLURB
        if kind in ("dialogue", "co_summarize", "co_supervisor", "co_readback", "co_outline"):
            return MOCK_DIALOGUE
        if kind == "idea":
            return "三个候选选题。"
        return self._prose(n)

    def _prose(self, n: int) -> str:
        return _mock_prose(n, self.prose_mult)

    def record(self, kind: str, slot: str, prompt: str) -> str:
        self.calls.append((kind, slot, prompt))
        return self.reply(kind, prompt)


class MockClient:
    def __init__(self, slot: str, rec: Recorder):
        self.slot = slot
        self.rec = rec

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, **kw):
        text = self.rec.record(self.rec.kind(prompt), self.slot, prompt)
        if on_chunk:
            for i in range(0, min(len(text), 150), 50):
                on_chunk(text[i:i + 50])
        return text

    def chat(self, prompt, **kw):
        return self.rec.record(self.rec.kind(prompt), self.slot, prompt)


class MockRouter:
    def __init__(self, rec: Recorder):
        self.rec = rec

    def client(self, slot: str):
        return MockClient(slot, self.rec)

    def total_tokens(self):
        return (0, 0)

    def estimate_cost(self):
        return 0.0

    def invalidate(self, *a, **kw):
        pass

    def refresh(self, *a, **kw):
        pass


# ---------------- 夹具书构建 ----------------

def build_book(root: str) -> str:
    proj = project.create_project(root, BOOK)
    project.write_idea_info(proj, GENRE, "番茄", IDEA, 30)
    project.ensure_tracking_files(proj)
    st.save_state(proj, {"genre_preset": PRESET, "total_chapters": 10,
                         "current_chapter": 1})
    return proj


def install_fixtures(proj: str):
    """覆盖 mock 生成的设定，使装配输入完全固定"""
    project.write_file(os.path.join(proj, "设定", "题材定位.md"), MOCK_CORE)
    project.write_file(os.path.join(proj, "大纲", "大纲.md"), MOCK_VOLUME)
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), WB_FIXTURE + WB_ADDITIONAL)
    project.write_file(os.path.join(proj, project.REGEX_PATH), RG_FIXTURE)
    memory_dir = os.path.join(proj, "追踪")
    project.write_file(os.path.join(memory_dir, "角色状态.md"),
                       "陈更：余额 0 天，右手食指完好\n柳三更：尚未查账\n")
    project.write_file(os.path.join(memory_dir, "伏笔.md"),
                       "| 伏笔 | 状态 | 登记章 |\n|---|---|---|\n| 第一枚指印 | 未回收 | 1 |\n")
    project.write_file(os.path.join(memory_dir, "时间线.md"), "（尚未登记）\n")
    project.write_file(os.path.join(memory_dir, "上下文.md"), "# 写作上下文\n\n（尚无）\n")


# ---------------- 跑全部装配点 ----------------

def run_all(proj: str, cfg: dict, rec: Recorder) -> None:
    from app.core import stages as st_mod
    from app.core import co_dialogue

    # 票数钉成 1：让审校调用次数与 _REVIEW_SEQ 步进一一对应（投票聚合另有单测）
    cfg.setdefault("gates", {})["review_votes"] = 1
    cfg["gates"]["review_votes_recheck"] = 1

    orch = orch_mod.Orchestrator(proj, cfg)
    orch.router = MockRouter(rec)
    rec._chapter[0] = 1

    st_mod.stage_core_setting(orch)
    st_mod.stage_volume_outline(orch, 30)
    st_mod.stage_worldbook_gen(orch)
    install_fixtures(proj)

    st.save_state(proj, {**st.load_state(proj), "stage": st.STAGE_CH_OUTLINE})
    st_mod.stage_chapter_outlines(orch, 1, 4)
    # (章号, 正文段数)：29 达标 / 20 不足→ENRICH 装配 / 45 超标→TRIM 装配
    for n, mult in [(1, 29), (2, 29), (3, 20), (4, 45)]:
        rec._chapter[0] = n
        rec.prose_mult = mult
        st.save_state(proj, {**st.load_state(proj), "stage": st.STAGE_PROSE})
        st_mod.chapter_microcycle(orch, n)
    rec.prose_mult = 29

    prose1 = _mock_prose(1)

    # 共写档：对话派单 / 手动查验审校 / 反哺 / 定稿总结 / 回读 / 监工
    co_dialogue.DialogueWorker(cfg, proj, st.STAGE_CW_PROSE, "把清账夜写出来",
                               router=MockRouter(rec), focus_chapter=1).run()
    co_dialogue.CwProseCheckWorker(cfg, proj, 1, prose1, mode="review",
                                   router=MockRouter(rec)).run()
    co_dialogue.CwProseCheckWorker(cfg, proj, 1, "他仿佛看到命运的齿轮在转。",
                                   mode="deslop", router=MockRouter(rec)).run()
    rec._chapter[0] = 2
    co_dialogue.MemoryBackflowWorker(cfg, proj, 2, _mock_prose(2),
                                     router=MockRouter(rec)).run()
    co_dialogue.SummarizeWorker(cfg, proj, st.STAGE_CW_PROSE,
                                router=MockRouter(rec)).run()

    # 简介与标签（桥层 worker，内部自建 ModelRouter → 打桩替换）
    import app.llm as llm_mod
    real_router = llm_mod.ModelRouter
    llm_mod.ModelRouter = lambda cfg_, **kw: MockRouter(rec)
    try:
        from app.ui import bridge as bridge_mod
        bridge_mod._BlurbWorker(cfg, proj).run()

        # 局部改写：SelectionRewriteWorker 在 __init__ 里用的 bridge.py:20 那个模块级
        # ModelRouter 名字（已绑定），只打 app.llm.ModelRouter 打不到它，会真去建
        # 路由发网络请求 —— 必须连 bridge 侧的绑定一起换掉。
        # 跑两种 mode：setting 带核心设定块，only 不带，两种 prompt 形状都要进护栏。
        real_bridge_router = bridge_mod.ModelRouter
        bridge_mod.ModelRouter = lambda cfg_, **kw: MockRouter(rec)
        try:
            for mode in ("setting", "only"):
                bridge_mod.SelectionRewriteWorker(
                    cfg, "他推门进去。", "灯芯只剩一线，像随时要断。", "阿栾在门外等着。",
                    "把这句写得更克制，别用比喻", mode=mode, proj=proj).run()
        finally:
            bridge_mod.ModelRouter = real_bridge_router
    finally:
        llm_mod.ModelRouter = real_router

    # 世界书直读口（预算/锚点行为也进基线）
    for budget, anchors in [(2000, None), (600, None),
                            (2000, project.worldbook_anchors(proj, 1))]:
        rec.calls.append(("worldbook_text", f"budget={budget}",
                          project.worldbook_text(proj, budget, anchors=anchors)))
    # 截断路径（W1 装配内核）：预算小于全文才走按章激活，逐章差异必须进护栏
    for num in (1, 2, 3):
        anchors = project.worldbook_anchors(proj, num)
        rec.calls.append(("worldbook_assemble", "budget=160 num=%d anchors=%s" % (num, anchors),
                          project.worldbook_text(proj, 160, anchors=anchors, num=num)))


# ---------------- 基线读写与比对 ----------------

def _norm(proj: str, text: str) -> str:
    """抹掉绝对路径与临时目录痕迹，保证跨机器哈希稳定"""
    text = text.replace(proj, "<PROJ>").replace(_FH, "<TMP>")
    return re.sub(r"[A-Za-z]:\\\\?[^ \n]*?探针书", "<PROJ>", text)


def digest(proj: str, rec: Recorder) -> list:
    out = []
    for i, (kind, slot, prompt) in enumerate(rec.calls):
        body = _norm(proj, prompt)
        out.append({"i": i, "kind": kind, "slot": slot, "chars": len(body),
                    "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()})
    return out


def _diff(old: list, new: list):
    """按 (kind, slot) 分组比对，**不把索引当键**。

    旧实现键是 (i, kind, slot)：中途插入一个新装配点会让其后每条同时报
    「消失 + 新增」，纯位移被读成内容变化 —— 于是「加一条装配点」这种正当
    改动变成不可审阅（也误触发「有消失就是 bug」的对账纪律）。
    分组后：组内条数变化 = 真的新增/消失；组内摘要集合变化 = 内容变化。
    """
    def group(entries):
        g = {}
        for e in entries:
            g.setdefault((e["kind"], e["slot"]), []).append(e)
        return g

    go, gn = group(old), group(new)
    lines = []
    for key in sorted(set(go) | set(gn)):
        kind, slot = key
        o, n = go.get(key, []), gn.get(key, [])
        if len(o) != len(n):
            lines.append(f"[调用次数] {kind}/{slot} {len(o)}→{len(n)} "
                         f"（新增装配点或该装配点少跑了一次）")
            continue
        os_ = sorted(o, key=lambda e: e["sha256"])
        ns_ = sorted(n, key=lambda e: e["sha256"])
        for oe, ne in zip(os_, ns_):
            if oe["sha256"] != ne["sha256"]:
                lines.append(f"[内容变化] {kind}/{slot} "
                             f"chars {oe['chars']}→{ne['chars']} (#{ne['i']})")
    return lines


def wiring_check(rec, proj: str) -> list:
    """P4 接线断言：预设里填了的字段、书里声明的 must 契约，
    都必须出现在承载它的那张最终 prompt 里

    基线只保证「字节不变」，字节不变地丢掉一个字段它测不出来——所以这里按
    装配点正向取词：用户填的每个字段、作者声明的每条 must，都要在它该在的地方出现。
    """
    from app import presets as genre_presets

    p = genre_presets.load_preset(PRESET)
    by_kind = {}
    for kind, _slot, prompt in rec.calls:
        by_kind.setdefault(kind, []).append(prompt)

    def merged(kind: str) -> str:
        return "\n".join(by_kind.get(kind) or [])

    all_prompts = "\n".join(_prompt for _k, _s, _prompt in rec.calls)

    # stage_hints 六键 → 承载它的装配点；review 的审校特化与 review_extra 同槽
    expect = [
        ("core_setting", "core"), ("outline", "volume"),
        ("worldbook", "worldbook_gen"), ("unit_outline", "outline"),
        ("prose", "prose"), ("review", "review"),
    ]
    fails = []
    for stage, kind in expect:
        if not by_kind.get(kind):
            fails.append(f"装配点 {kind} 本次未出现，无法验证 {stage} 特化")
            continue
        val = ((p.get("stage_hints") or {}).get(stage) or "").strip()
        if not val:
            fails.append(f"夹具预设 {PRESET} 未填 stage_hints.{stage}，测不到东西")
        elif val not in merged(kind):
            fails.append(f"stage_hints.{stage} 未进 {kind} prompt")
    for key, label in genre_presets.PRESET_FIELDS:
        val = (p.get(key) or "").strip()
        if not val:
            fails.append(f"夹具预设未填 {key}（{label}）")
            continue
        if key == "deslop_extra":
            # 专属近端槽：写作与去味改写两处都要在，只补一处等于扩写/压缩仍在裸写
            for kind in ("prose", "deslop", "enrich", "trim"):
                if by_kind.get(kind) and val not in merged(kind):
                    fails.append(f"deslop_extra 未进 {kind} prompt（红线段断链）")
        elif key == "review_extra":
            if "review" in by_kind and val not in merged("review"):
                fails.append("review_extra 未进 review prompt")
        elif val not in all_prompts:
            fails.append(f"{key}（{label}）在任何装配点都没出现")

    # —— must 契约接线：每条 must 都要出现在会改正文的装配点里 ——
    # 扩写/压缩/去味/局部改写四张模板历史上不带契约，而它们全在整章/整段重写正文；
    # 少一条 = 那一步在裸写，只能等终审概率性抓。规则文本从 regex_rules 动态取，
    # 免得改了夹具 RG_FIXTURE 之后这条断言悄悄变成空转。
    _MUST_KINDS = ("prose", "enrich", "trim", "deslop", "selection", "review")
    must_rules = [r["rule"] for r in project.regex_rules(proj, "logic")
                  if r["level"] == "must"]
    if not must_rules:
        fails.append("夹具 正则.md 没有 must 级规则，must 接线断言将空转")
    for kind in _MUST_KINDS:
        if not by_kind.get(kind):
            fails.append(f"装配点 {kind} 本次未出现，无法验证 must 契约接线")
            continue
        for rule in must_rules:
            if rule not in merged(kind):
                fails.append("must 契约「%s…」未进 %s prompt（该步在裸写正文）"
                             % (rule[:20], kind))
    return fails


def main() -> int:
    update = "--update-baseline" in sys.argv
    home = os.path.join(_FH, "books")
    os.makedirs(home, exist_ok=True)
    cfg = cfg_mod.load_config()
    proj = build_book(home)
    rec = Recorder()
    run_all(proj, cfg, rec)
    entries = digest(proj, rec)
    print(f"装配点调用次数={len(entries)}  "
          f"唯一 kind={sorted({e['kind'] for e in entries})}")

    fails = wiring_check(rec, proj)
    if fails:
        print(f"WIRING FAIL {len(fails)} 处预设字段断链：")
        for ln in fails:
            print("  " + ln)
        return 1
    print("WIRING PASS 预设字段全部落到承载它的 prompt")

    if update or not os.path.exists(BASELINE):
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump({"count": len(entries), "entries": entries}, f,
                      ensure_ascii=False, indent=1)
        print(("基线已刷新 → " if update else "首建基线 → ") + BASELINE)
        return 0

    with open(BASELINE, encoding="utf-8") as f:
        old = json.load(f)["entries"]
    lines = _diff(old, entries)
    if not lines:
        print(f"PASS 零漂移（{len(entries)} 个装配调用与基线逐字一致）")
        return 0
    print(f"DRIFT {len(lines)} 处漂移：")
    for ln in lines[:60]:
        print("  " + ln)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_FH, ignore_errors=True)
