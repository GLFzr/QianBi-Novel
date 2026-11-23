# -*- coding: utf-8 -*-
"""主写 AI 调度器：QThread 中运行总流水线，事件经 Qt 信号推到 UI

- 断点续跑：从 pipeline_state.json 与项目文件推断进度，缺什么补什么
- 暂停：当前 LLM 调用返回后停（checkpoint 语义）
- 停止：尽快在安全点退出
- 失败现场：异常时把最后 prompt / 日志尾部 dump 到项目 pipeline_debug/
"""
import logging
import os
import re
import threading
import time

from PySide6.QtCore import QThread, Signal

from .. import project
from .. import diagnostics
from ..llm import ModelRouter
from . import anomaly_persist   # S6a：导入即向 ledger_view 装订告警落账（core→core 合法）
from . import ledger_view as lv   # S6a：台账视图/告警查询（原 usage 上探已拆，core→core）
from . import stages, state as st
from .stages import StageError, PipelineStopped

logger = logging.getLogger("qianbi.core")

OUTLINE_BATCH = 2  # 细纲每批生成章数（max 思考下 5 章批会被推理吃光输出预算，2 章批实测稳定）

LOG_TAIL_MAX = 50  # 日志环形缓冲条数（失败 dump 用）

G4_PAUSE_AFTER = 2  # 相位看门狗：连续 N 章记账产物缺失 → auto_pause（T3 连停 30 章的翻案线）

# D1 预算宪法出厂值（0.20.3，源自 AI-Novel-Writer generation-harness 的会话级硬顶）：
# 可被 writing.gen_budget 全量覆盖；0/负值=该轴不设限。
GEN_BUDGET_DEFAULTS = {"max_calls": 32, "max_total_tokens": 147456,
                       "max_single_tokens": 32768, "max_minutes": 60}


class GenBudget:
    """章生成周期预算表（D1）：调用次数/累计 tokens/单次峰值/耗时四轴硬顶计数器。

    数据源 = app.llm.client 的调用观察者事件（每个网关回了 usage 的物理响应一条，
    含 W-4 白付的 empty/abort/retry；网关全程不回 usage 的失败不计次，时长轴兜底）。
    轴口径：
      calls         物理响应次数（不是逻辑调用——重试白付同样烧真钱，一并计）
      total_tokens  章周期累计 in+out（网关实报口径，盲区不算）
      single_tokens 单次响应 in+out 峰值（宪法原意是「单次输出意图上限」，intent
                    我方事后不可知，以实耗峰值记账——诚实口径）
      minutes       章周期墙钟耗时
    feed 从 LLM 工作线程到账，exceeded/receipt 从流水线线程查询——纯数字读改，
    单轴更新原子（CPython GIL），不加锁。
    """

    AXES = ("max_calls", "max_total_tokens", "max_single_tokens", "max_minutes")

    def __init__(self, limits: dict = None):
        self.configure(limits)
        self.reset()

    def configure(self, limits: dict = None):
        """装载上限（缺省键回出厂值；垃圾值按 0=不设限处理——诚实放行好过误杀）"""
        src = dict(GEN_BUDGET_DEFAULTS)
        src.update(limits or {})
        out = {}
        for k in self.AXES:
            try:
                v = float(src.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0   # 垃圾值按「不设限」处理（诚实放行好过误杀）
            out[k] = v if v > 0 else 0.0   # 0/负统一归 0=该轴不设限
        self.limits = out

    def reset(self, num: int = 0):
        """本章窗口重开（orchestrator 每章起点调用；计数归零、计时重起）"""
        self.num = int(num or 0)
        self.calls = 0
        self.total_tokens = 0
        self.single_tokens = 0
        self.t0 = time.monotonic()
        self.tripped = False      # 本窗口已熔断（一章只熔一次，重跑算新窗口）
        self.violations = []      # 触发时违限轴清单（回执用）

    @property
    def elapsed_minutes(self) -> float:
        return (time.monotonic() - self.t0) / 60.0

    def feed(self, tin: int = 0, tout: int = 0, **_):
        """一次物理调用到账（client 观察者事件）。返回违限轴列表（空=未超限）"""
        self.calls += 1
        used = int(tin or 0) + int(tout or 0)
        self.total_tokens += used
        self.single_tokens = max(self.single_tokens, used)
        return self.exceeded()

    def exceeded(self) -> list:
        """任一轴超限的轴名清单（空=未超限）；0/负上限的轴不参与判定"""
        lim = self.limits
        v = []
        if lim["max_calls"] > 0 and self.calls > lim["max_calls"]:
            v.append("max_calls")
        if lim["max_total_tokens"] > 0 and self.total_tokens > lim["max_total_tokens"]:
            v.append("max_total_tokens")
        if lim["max_single_tokens"] > 0 and self.single_tokens > lim["max_single_tokens"]:
            v.append("max_single_tokens")
        if lim["max_minutes"] > 0 and self.elapsed_minutes > lim["max_minutes"]:
            v.append("max_minutes")
        return v

    def receipt(self, violations: list = None) -> dict:
        """预算消耗回执（超限时随异常落账；只含计数与上限，无 prompt 无正文）"""
        v = self.violations if violations is None else violations
        return {"ch": self.num, "calls": self.calls,
                "total_tokens": self.total_tokens,
                "single_tokens": self.single_tokens,
                "minutes": round(self.elapsed_minutes, 1),
                "limits": dict(self.limits), "violated": list(v)}

    def receipt_text(self, violations: list = None) -> str:
        """回执人话版（次数/tokens/分钟/章号），日志与异常台账共用一份措辞"""
        r = self.receipt(violations)
        lim = r["limits"]
        return (f"第 {r['ch']} 章预算消耗报告——调用 {r['calls']} 次（顶 {lim['max_calls']:.0f}），"
                f"tokens {r['total_tokens']}（顶 {lim['max_total_tokens']:.0f}），"
                f"单次峰值 {r['single_tokens']}（顶 {lim['max_single_tokens']:.0f}），"
                f"耗时 {r['minutes']} 分钟（顶 {lim['max_minutes']:.0f}）；"
                f"违限轴：{'+'.join(r['violated']) or '无'}")


class Orchestrator(QThread):
    sig_log = Signal(str, str)          # level, msg
    sig_stage = Signal(str)             # 当前总阶段 key
    sig_chapter_started = Signal(int)
    sig_step = Signal(int, str)         # 章号, 微循环步骤 key
    sig_stream_chunk = Signal(str)      # LLM 流式输出增量（写作工作台实时显示）
    sig_stream_stage = Signal(str)      # 流式阶段切换（草稿/去味/审校…），UI 清空流式区并显示标签
    sig_stream_reasoning = Signal(str)  # 思维链增量（默认隐藏，用户主动查看）
    sig_thinking = Signal(str, str, int, str)  # T4.3 M1：思维链（槽位, 阶段, 章号, 增量）→ Console 留存
    sig_chapter_done = Signal(dict)     # 章节记录
    sig_queue = Signal()                # 队列数据变化，通知 UI 刷新
    sig_finished = Signal(str)          # done / stopped
    sig_failed = Signal(str)
    sig_auto_paused = Signal(str)       # 闸门自动暂停（strict 策略），带原因
    sig_gate = Signal(str, int, str)    # 步骤决策门：gate_key, chapter, summary
    sigGateDetail = Signal(str, int, dict)   # Q6（只加不改）：九门停靠详情伴随信号——旧 sig_gate 位置参数与语义不动

    # Q6：九门停靠指导（拦哪条 / 继续与回退的后果）。决策门的「拦哪条」是门语义
    # 本身；字数/正则硬闸的当前值与阈值在 bridge 锁定路径里有真值，不在此表。
    GATE_GUIDANCE = {
        "G1": {"blocked": "核心设定是否成立——缺核心冲突、金手指机制不闭合、世界观自相矛盾就该拦下",
               "continue": "设定按当前文本冻结，进入全书大纲阶段",
               "rollback": "当前设定归档后重拟，已生成的大纲/细纲连带清空"},
        "G2": {"blocked": "全书大纲是否成立——卷级结构断裂、主线推进缺阶段、结尾无回收就该拦下",
               "continue": "大纲文本冻结，进入细纲批生成",
               "rollback": "当前大纲归档后重拟，细纲连带清空"},
        "G3": {"blocked": "本批细纲是否成立——章与章不衔接、节拍缺钩子、与大纲冲突就该拦下",
               "continue": "本批细纲冻结，继续下一批或进入素材组装",
               "rollback": "本批细纲归档，可带想法重拟本批（其余批不动）"},
        "G4": {"blocked": "素材组装是否完备——材料缺口、伏笔未登记、设定遗漏就该拦下",
               "continue": "材料按当前清单投入本章写作",
               "rollback": "归档组装清单重组装（未消费材料可重选）"},
        "G5L": {"blocked": "本章开写条件（软门）——字数目标、前章钩子、视角衔接提醒；无产物可回退",
                "continue": "开始写本章正文",
                "rollback": "软门无产物，只带想法重新确认即可"},
        "G6": {"blocked": "AI 味扫描结果确认——本地扫描检出的问题清单是否要处理",
               "continue": "按当前扫描结论进入去味/下一步",
               "rollback": "保留原稿跳过去味（扫描记录照常留痕）"},
        "G7": {"blocked": "去味改写前后对比确认——改写是否引入新问题、是否漏检",
               "continue": "去味稿生效，进入审校",
               "rollback": "还原去味前原稿，本次改写作废"},
        "G8": {"blocked": "审校结论确认——人工审校=你录入的阻断问题清单；AI 审校=六维投票结论",
               "continue": "结论生效进入定稿（G9 字数/正则仍把关）",
               "rollback": "还原审校前原稿，本轮审校作废"},
        "G9": {"blocked": "定稿确认——字数闸门（目标下限 90%）与正则 must 契约未过会拦",
               "continue": "本章锁定进版本历史，触发剧情反哺",
               "rollback": "归档本章重写（旧版本保留在版本历史）"},
    }

    def __init__(self, proj: str, cfg: dict, parent=None):
        super().__init__(parent)
        self.proj = proj
        self.cfg = cfg
        # 预设参数覆盖两层（P1）：采样基线打底 + 阶段档压顶；建路由先装一次，章循环里按「下一章生效」重绑
        self.router = ModelRouter(cfg, **stages.preset_param_layers(proj))
        self._pause = threading.Event()
        self._resume_evt = threading.Event()   # 暂停唤醒事件（T3.3：去 0.15s 轮询）
        self._stop = False
        # 步骤决策门（Step Gates）：每一决策点等待人确认 → 继续/带想法继续/回退重做
        self._gate_evt = threading.Event()     # 门等待事件（置位=人已决策）
        self._gate_idea = ""                   # 人提交的想法（注入下一步/重跑步骤）
        self._gate_return = False              # True=回退重做请求
        self._gate_return_target = ""          # 回退目标门键（默认上一步=当前门）
        self._gate_pending = ""                # 当前等待中的门键
        # 章间传递的"门想法"（G9 的想法可注入下一章；G2 的想法注入细纲）
        self._gate_carry_idea = ""
        # 失败现场（stages 在每次 LLM 调用前写入）
        self.last_prompt = ""
        # 最近一次 6 维审校的原始输出（反馈环根因解析专用；与 last_prompt 的输入语义区分）
        self.review_raw = ""
        self._log_tail = []             # 最近日志（环形）
        self._cur_stage = ""
        self._cur_num = 0
        self._cur_step = ""
        # S1 卷级会话栈（writing.volume_session，默认关）：按卷号缓存 VolumeSession，
        # 生命周期挂本次 run（每次连跑一个实例集；run() 启动时清空，断点恢复由
        # stages 首次取用时从 项目/会话/卷N_messages.jsonl 装载）。flag 关闭时
        # 这张表永不被触达，章会话路径行为逐字节不变。
        self.volume_sessions = {}
        # C35 G4 相位看门狗：连续缺失计数与去重游标（章循环收尾维护）
        self._g4_missing_run = 0
        self._g4_last_missing = 0
        # D1 预算宪法：章生成周期计数器（观察者在 run() 注册；窗口每章重开）
        self._budget = GenBudget((cfg or {}).get("writing", {}).get("gen_budget"))
        self._budget_active = False

    # ---------- 外部控制 ----------

    def pause(self):
        self._pause.set()
        self._resume_evt.clear()

    def resume(self):
        self._pause.clear()
        self._resume_evt.set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    @property
    def stopped(self) -> bool:
        """只读停止标志：供流式循环当 abort 谓词轮询（checkpoint 之外的唯一实时出口）"""
        return self._stop

    def stop(self):
        self._stop = True
        self._pause.clear()
        # 唤醒所有直等中的阻塞点（T3.3）：暂停等待/门等待立即退出并走停止分支
        self._resume_evt.set()
        self._gate_evt.set()

    def auto_pause(self, reason: str):
        """质量闸门自动暂停（strict 策略）：置暂停位 + 通知 UI，等人处理后续跑"""
        self._pause.set()
        self.log("warn", f"闸门暂停：{reason}（处理后可点「继续」）")
        self.sig_auto_paused.emit(reason)

    # ---------- C35 G4：相位看门狗（记账对账）----------

    def _chapter_bookkeeping_ok(self, num: int) -> bool:
        """第 N 章正文已落库 ⇒ 记账产物必须存在的本地零成本校验。

        章级可验证的记账证据取两路并集（追踪四文件是累积件、无章级指纹，其存在性
        由 ensure_tracking_files 保证；对账只认章级证据）：
          1. usage 台账该章出现过任一记账相位行（tracking/chapter_summary/
             global_summary/canon_audit）——记账调用发生过的直接痕迹；
          2. 追踪/章节摘要.md 存在第 N 章条目——记账产物本体（台账行缺失但产物
             真实写成了的场景，如他进程写入后本进程内存视图未刷新）。
        两路皆缺 =「正文已落库、收尾记账窗口被中断」（T3 记账停摆 30 章的指纹）。
        """
        if lv.chapter_accounted(num):
            return True
        try:
            with open(os.path.join(self.proj, "追踪", "章节摘要.md"),
                      encoding="utf-8") as f:
                pat = re.compile(r"^-\s*第%d章[《\s]" % int(num))
                return any(pat.match(ln.strip()) for ln in f)
        except OSError:
            return False

    def _watch_phase_products(self, num: int):
        """章循环收尾的相位看门狗（append_history 后、G9 门之前调用）。

        缺失 → error 日志 + 异常落账（state.anomalies / session_events）；
        连续 G4_PAUSE_AFTER 章缺失 → auto_pause（复用闸门暂停机制，等人处理）。
        看门狗自身故障只 warn，绝不阻断主流水线。
        """
        try:
            ok = self._chapter_bookkeeping_ok(num)
        except Exception as e:  # noqa: BLE001
            self.log("warn", f"相位看门狗自检失败（不阻断）：{e}")
            return
        if ok:
            self._g4_missing_run = 0
            self._g4_last_missing = 0
            return
        if self._g4_last_missing != num:   # 同章重跑（G9 回退）不计「连续」
            self._g4_missing_run += 1
            self._g4_last_missing = num
        msg = (f"第 {num} 章正文已落库，但记账产物缺失（台账无 tracking/摘要相位行，"
               f"章节摘要链亦无本章条目）——收尾记账窗口被中断的典型信号")
        self.log("error", msg)
        try:
            lv.report_anomaly("bookkeeping_missing", "error", ch=num, msg=msg,
                              source="G4")
        except Exception as e:  # noqa: BLE001
            logger.debug("G4 告警落账失败（忽略）: %s", e)
        if self._g4_missing_run >= G4_PAUSE_AFTER:
            self.auto_pause(f"G4 相位看门狗：连续 {self._g4_missing_run} 章记账产物"
                            f"缺失（正文已落库而追踪/摘要未更新）")

    # ---------- D1 预算宪法（章生成周期硬顶+熔断）----------

    def _on_llm_call(self, ev: dict):
        """client 调用观察者：章窗口内计数，任一轴超限即熔断（LLM 工作线程到账）。

        观察者侧已兜异常，这里再兜一层——预算是观测件，绝不碰调用链。
        """
        try:
            if not self._budget_active or self._budget.tripped:
                return
            v = self._budget.feed(tin=ev.get("tin", 0), tout=ev.get("tout", 0))
            if v:
                self._budget.tripped = True
                self._budget.violations = list(v)
                self._budget_trip(v)
        except Exception as e:  # noqa: BLE001
            logger.debug("预算计数失败（忽略）: %s", e)

    def _budget_trip(self, violations: list):
        """熔断三连：消耗回执（error 日志）+ 异常落账（C35 G5 通道，规则
        gen_budget_exceeded → state.anomalies + session_events）+ 闸门暂停
        （sig_auto_paused → UI toast）。之后下一个 checkpoint 即停等人处置。"""
        text = self._budget.receipt_text(violations)
        rep = self._budget.receipt(violations)
        self.log("error", f"预算熔断：{text}")
        try:
            lv.report_anomaly("gen_budget_exceeded", "error", ch=rep["ch"], msg=text,
                              calls=rep["calls"], total_tokens=rep["total_tokens"],
                              single_tokens=rep["single_tokens"],
                              minutes=rep["minutes"],
                              violated="+".join(violations))
        except Exception as e:  # noqa: BLE001
            logger.debug("预算熔断落账失败（忽略）: %s", e)
        self.auto_pause(f"预算宪法熔断：第 {rep['ch']} 章 {'+'.join(violations)} "
                        f"超限（调用{rep['calls']}次/tokens {rep['total_tokens']}/"
                        f"{rep['minutes']}分钟），已暂停等人处置")

    def _budget_finish(self):
        """本章窗口收口：关闭观察计数 + 末次裁决（最后一次调用到账后磨掉的
        时间/尾差越限，在这里兜住——观察者只评「调用到账」时刻）。"""
        self._budget_active = False
        if self._budget.tripped:
            return
        v = self._budget.exceeded()
        if v:
            self._budget.tripped = True
            self._budget.violations = list(v)
            self._budget_trip(v)

    # ---------- 步骤决策门（Step Gates）----------

    def gate_enabled(self, key: str) -> bool:
        """门停靠判定（v1.2 两档制）：纯门预置驱动——
        step=逐步确认（全接线门停）/ border=边界确认（按 gate_list 勾选）/ off=全放行。
        run_mode 不再参与判定；共写档根本进不了流水线（startPipeline 前置拦截）"""
        w = self.cfg.get("writing", {})
        preset = str(w.get("gate_preset", "off"))
        if preset == "step":
            return True
        if preset == "border":
            return key in (w.get("gate_list") or [])
        return False

    def gate(self, key: str, summary: str = "", chapter: int = 0) -> str:
        """停在决策门等人确认。返回人提交的想法（空=直接继续）。
        回退重做在解锁前由 _apply_rollback 处理，本方法不返回"""
        if not self.gate_enabled(key):
            return ""
        # F3 连写会话：writing.auto_gate 开启时全部决策门自动放行（批量跑批用）
        if (self.cfg or {}).get("writing", {}).get("auto_gate"):
            self.log("info", f"[连写] 决策门 {key} 自动放行")
            return ""
        # 暂停优先于决策门：暂停态下弹门会出现两个语义不同的「继续」按钮
        # （门条的 resolveStepGate 与流水线的 resumePipeline），用户无从判断点哪个。
        # 先过 checkpoint 停在步骤边界，等用户恢复后再来要这个决策。
        self.checkpoint()
        state = st.load_state(self.proj)
        # L2-11：源头不再截断 [:200]——QML 换行上限拿不到全量，摘要完整性交给界面控制
        state["gate_status"] = {"gate": key, "chapter": chapter,
                                "summary": summary, "ts": time.time()}
        st.save_state(self.proj, state)
        self._gate_evt.clear()
        self._gate_idea = ""
        self._gate_return = False
        self._gate_pending = key
        self.log("info", f"决策门 {key}（第{chapter}章）等待你的决定：{summary[:60]}")
        self.sig_gate.emit(key, chapter, summary)
        # Q6：详情伴随信号——界面必须能答出「拦哪条 / 当前值 vs 阈值 / 继续与回退
        # 分别发生什么」。决策门本身无数值阈值（诚实给空串），字数/正则硬闸的
        # 当前值与阈值走 bridge.lockBlockedDetail（有真值才填）。
        g = self.GATE_GUIDANCE.get(key, {})
        self.sigGateDetail.emit(key, chapter, {
            "gate_key": key,
            "blocked_rule": g.get("blocked", ""),
            "current_value": "",
            "threshold": "",
            "violations": [],
            "continue_consequence": g.get("continue", ""),
            "rollback_consequence": g.get("rollback", ""),
        })
        # 直等决策（T3.3）：stop() 会置位 _gate_evt 立即唤醒；1s 超时仅兜底
        while not self._gate_evt.wait(1.0):
            if self._stop:
                raise PipelineStopped()
        if self._stop:
            raise PipelineStopped()
        self._gate_pending = ""
        idea = self._gate_idea
        self._gate_idea = ""
        ret = self._gate_return
        self._gate_return = False
        if ret:
            self._apply_rollback(key, chapter)
            # 回退后：携带的想法留给重跑步骤注入；并让主循环重跑缺失产物
            self._gate_carry_idea = idea or self._gate_carry_idea
            return None  # 调用方据此知晓发生了回退
        return idea

    def resolve_gate(self, action: str, idea: str) -> bool:
        """UI 线程调用：next / return 决策，返回是否成功送达"""
        if not self._gate_pending:
            return False
        self._gate_idea = (idea or "").strip()
        self._gate_return = (action == "return")
        self._gate_evt.set()
        return True

    def consume_gate_idea(self) -> str:
        """取走章间携带的想法（G9→下一章 / 回退后→重跑注入）"""
        idea = self._gate_carry_idea
        self._gate_carry_idea = ""
        return idea

    def _apply_rollback(self, key: str, chapter: int):
        """回退动作：把目标产物归档后删除 → 主循环按「缺失即重跑」自动重做"""
        import shutil
        import datetime
        ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
        if not self.proj:
            return
        roll = os.path.join(self.proj, "pipeline_debug", "rollback", f"{key}_ch{chapter}_{ts}")
        try:
            if key == "G1":  # 回退重拟核心设定（v1.2 接线）
                os.makedirs(roll, exist_ok=True)
                t = os.path.join(self.proj, "设定", "题材定位.md")
                if os.path.exists(t):
                    shutil.copy2(t, os.path.join(roll, os.path.basename(t)))
                    os.remove(t)
                    self.log("warn", "G1 回退：核心设定已归档并清除，将重新生成")
            elif key == "G3":  # 回退重拟本批细纲（v1.2 接线）：归档清除批次区间内细纲
                os.makedirs(roll, exist_ok=True)
                start = chapter or 0
                removed = []
                for n in range(start, start + OUTLINE_BATCH):
                    p = project.get_outline_path(self.proj, n)
                    if os.path.exists(p):
                        shutil.copy2(p, os.path.join(roll, os.path.basename(p)))
                        os.remove(p)
                        removed.append(n)
                if removed:
                    self.log("warn", f"G3 回退：第 {removed[0]}~{removed[-1]} 章细纲已归档并清除，将重拟本批")
            elif key == "G2":  # 回退重拟全书大纲（连带清空细纲，避免旧细纲对账过期）
                os.makedirs(roll, exist_ok=True)
                targets = [os.path.join(self.proj, "大纲", "大纲.md")]
                outlines_dir = os.path.join(self.proj, "大纲")
                for n, p in project.list_outlines(self.proj):
                    targets.append(p)
                for t in targets:
                    if os.path.exists(t):
                        shutil.copy2(t, os.path.join(roll, os.path.basename(t)))
                        os.remove(t)
                # 大纲回退后把细纲已删除，需同步清空状态中的相关计划提示
                self.log("warn", "G2 回退：全书大纲与全部细纲已归档并清除，将重新生成")
            elif key == "G9":  # 回退重写本章：归档章节文件，版本历史保留（v1 仍在）
                # M4 锁守卫：locked 章直接拒绝（「该章已锁定，请先在共写档显式解锁」）
                if project.is_chapter_locked(self.proj, chapter):
                    self.log("warn", f"G9 回退拒绝：第 {chapter} 章已终稿锁定，请先在共写档显式解锁")
                    return
                os.makedirs(roll, exist_ok=True)
                for n, name, path in project.list_chapters(self.proj):
                    if n == chapter:
                        shutil.copy2(path, os.path.join(roll, os.path.basename(path)))
                        os.remove(path)
                        self.log("warn", f"G9 回退：第 {chapter} 章已归档并清除（版本历史保留），将重写本章")
                        break
            elif key in ("G4", "G6", "G7", "G8"):
                # 内侧门（T4.1）：回退由章节微循环内部处理（重新组装/保留原稿），此处不动物料
                self.log("info", f"门 {key} 回退：由章节微循环内部处理（重新组装/保留原稿语义）")
            else:
                self.log("warn", f"门 {key} 暂不支持回退，已按继续处理")
        except Exception as e:  # noqa: BLE001
            self.log("error", f"回退动作失败（{e}），已按继续处理")
            self._gate_return = False

    # ---------- stage ctx 接口 ----------

    def log(self, level: str, msg: str):
        self.sig_log.emit(level, msg)
        self._log_tail.append(f"[{level}] {msg}")
        if len(self._log_tail) > LOG_TAIL_MAX:
            del self._log_tail[: len(self._log_tail) - LOG_TAIL_MAX]
        (logger.info if level == "ok" else
         logger.warning if level == "warn" else
         logger.error if level == "error" else logger.info)(msg)

    def step(self, num: int, step_key: str):
        self._cur_num = num
        self._cur_step = step_key
        self.sig_step.emit(num, step_key)

    def stream_chunk(self, text: str):
        """LLM 流式增量 → UI（写作工作台实时显示）"""
        self.sig_stream_chunk.emit(text)

    def stream_stage(self, label: str):
        """流式阶段切换 → UI（清空流式区 + 显示阶段标签）"""
        self.sig_stream_stage.emit(label)

    def stream_reasoning(self, text: str):
        """思维链增量 → UI（默认不展示，用户主动打开才看）"""
        self.sig_stream_reasoning.emit(text)

    def stream_thinking(self, slot: str, text: str):
        """思维链增量（带槽位上下文）→ Agent Console 分组留存（T4.3 M1）"""
        self.sig_thinking.emit(slot, self._cur_stage or "", self._cur_num, text)

    def checkpoint(self):
        # D1 预算宪法：时长轴的章内兜底裁决——观察者只在调用到账时评，两次调用
        # 之间磨掉的时间越限，在下一个 checkpoint 立即熔断（不等章尾收口）
        if self._budget_active and not self._budget.tripped:
            _v = self._budget.exceeded()
            if _v:
                self._budget.tripped = True
                self._budget.violations = list(_v)
                self._budget_trip(_v)
        if self._stop:
            raise PipelineStopped()
        while self._pause.is_set():
            # 直等唤醒（T3.3）：resume()/stop() 置位 _resume_evt；1s 超时兜底
            self._resume_evt.wait(1.0)
            if self._stop:
                raise PipelineStopped()
        if self._stop:   # stop() 唤醒时 _pause 已被清，出循环后再查一次
            raise PipelineStopped()
        # 离峰挂机（v0.19）：开启后 peak 时段在阶段边界等待，off-peak 自动续跑
        # （v4 分时价 off-peak 全线半价；设置面板「离峰挂机」开关）
        if (self.cfg or {}).get("writing", {}).get("offpeak_run"):
            from .offpeak import is_peak, wait_until_offpeak
            from datetime import datetime, timezone
            if is_peak(datetime.now(timezone.utc)):
                self.log("info", "离峰挂机：当前为 DeepSeek 高价时段，等待半价时段续跑…")
                wait_until_offpeak(log=self.log, stop_check=lambda: self._stop)

    # ---------- 主流程 ----------

    def run(self):
        from ..llm import client as llm_client
        llm_client.add_call_observer(self._on_llm_call)   # D1：章周期计数接入口
        try:
            self.volume_sessions = {}   # S1：卷会话实例随本次连跑重建（每卷一个）
            # C35 G5：登记告警落账目标——此后 record() 命中规则 → 本项目
            # state.anomalies + session_events；阈值随 cfg.usage_alerts 下发
            # （S6a：set_project 迁 core.ledger_view，usage 侧仅门面转发）
            lv.set_project(self.proj, self.cfg)
            project.ensure_tracking_files(self.proj)
            state = st.load_state(self.proj)
            # 恢复上次回退时持久化的用户想法（G2 回退后重启仍携带）
            if state.get("carry_idea"):
                self._gate_carry_idea = state.pop("carry_idea", "")
                st.save_state(self.proj, state)

            # 阶段① 核心设定（缺失才生成）
            if not os.path.exists(os.path.join(self.proj, "设定", "题材定位.md")):
                state["stage"] = st.STAGE_SETTING
                st.save_state(self.proj, state)
                self._cur_stage = st.STAGE_SETTING
                self.sig_stage.emit(st.STAGE_SETTING)
                stages.stage_core_setting(self)
                self.sig_queue.emit()
                # 决策门 G1（v1.2 裁决接线）：核心设定完成 → 人确认/提想法/回退重拟
                self.checkpoint()
                g1_idea = self.gate("G1", "核心设定已生成（设定/题材定位.md）。下一步：全书大纲。",
                                    chapter=0)
                if g1_idea is None:
                    # 回退：设定已归档清除，结束本次运行（缺失即重跑，携带的想法持久化注入重拟）
                    state = st.load_state(self.proj)
                    state["stage"] = st.STAGE_SETTING
                    if self._gate_carry_idea:
                        state["carry_idea"] = self._gate_carry_idea
                    st.save_state(self.proj, state)
                    # P0-2（评估修复）：归一收尾——不发 finished 会让 bridge 永远认为在跑
                    self.sig_finished.emit("stopped")
                    return
                if g1_idea:
                    self._gate_carry_idea = g1_idea  # 注入重拟/下一阶段
                state["stage"] = st.STAGE_OUTLINE
                st.save_state(self.proj, state)

            # 阶段② 全书大纲（缺失才生成）
            if not os.path.exists(os.path.join(self.proj, "大纲", "大纲.md")):
                self._cur_stage = st.STAGE_OUTLINE
                self.sig_stage.emit(st.STAGE_OUTLINE)
                stages.stage_volume_outline(self)
                self.sig_queue.emit()
                # 决策门 G2：大纲完成 → 人确认/提想法/回退重拟
                self.checkpoint()
                g2_idea = self.gate("G2", "全书大纲已生成。下一步：规划总章数并进入章节细纲。",
                                    chapter=0)
                if g2_idea is None:
                    # 回退：大纲与细纲已归档清除，重新走「缺失即重跑」
                    state = st.load_state(self.proj)
                    state["total_chapters"] = 0
                    if self._gate_carry_idea:
                        state["carry_idea"] = self._gate_carry_idea  # 重启后注入细纲
                    st.save_state(self.proj, state)
                    # P0-2（评估修复）：与 G1 回退同款——归一收尾，防运行态卡死（旧遗留 bug）
                    self.sig_finished.emit("stopped")
                    return  # 结束本次运行，等待用户再次点「开始」重跑（细纲层将带想法）
                if g2_idea:
                    self._gate_carry_idea = g2_idea  # 注入首批细纲
            else:
                # 大纲已存在（续跑）：若上次回退留下想法，带进细纲
                pass

            # 阶段②.5 世界书首版（仅当缺失/为空；对已有世界书的书零影响）
            wb_path = os.path.join(self.proj, "设定", "世界书.md")
            if not project.read_file(wb_path).strip():
                stages.stage_worldbook_gen(self)
                self.sig_queue.emit()

            # 计划总章数
            chapter_words = self.cfg.get("writing", {}).get("chapter_word_target", 3000)
            total = state.get("total_chapters", 0) or project.planned_chapters(self.proj, chapter_words)
            if total and state.get("total_chapters") != total:
                state["total_chapters"] = total
                st.save_state(self.proj, state)

            # 阶段③④ 正文循环（细纲按需自动补）
            # 起点取首个缺失章：中间章被「重写本章」删除后从缺口续跑（真机缺陷①修复）；
            # 缺口之后的已定稿章逐个跳过，不重写。
            num = project.first_missing_chapter(self.proj)
            done_nums = project.chapter_nums(self.proj)
            while total == 0 or num <= total:
                self.checkpoint()
                # 每章重绑预设参数两层：暂停期间用户换预设 → 下一章生效（与题材块同一口径）
                self.router.set_preset_params(**stages.preset_param_layers(self.proj))
                stages.begin_gen_trace(self)   # P2 轨迹容器：本章细纲/正文/审校各次调用都记在这里
                if num in done_nums:
                    num += 1
                    continue
                # D1 预算宪法：本章生成周期窗口重开（细纲批与微循环都在窗口内计数；
                # 上一章的消耗不带入——正常章零误伤的前提）
                self._budget.reset(num)
                self._budget_active = True
                if not os.path.exists(project.get_outline_path(self.proj, num)):
                    self._cur_stage = st.STAGE_CH_OUTLINE
                    self.sig_stage.emit(st.STAGE_CH_OUTLINE)
                    # 决策门 G3（v1.2 裁决接线）：本批细纲完成 → 确认/带想法重拟本批。
                    # 回退由 _apply_rollback 归档清除本批细纲，循环内重拟（上限 3 次防死循环）。
                    for _g3_try in range(3):
                        # L1-16：尾批按总章数截断（旧实现会给 total+1 章生成细纲并虚报门摘要）
                        _end = min(num + OUTLINE_BATCH - 1, total) if total else num + OUTLINE_BATCH - 1
                        stages.stage_chapter_outlines(self, num, _end)
                        self.sig_queue.emit()
                        g3_idea = self.gate(
                            "G3",
                            f"第 {num}~{_end} 章细纲已生成。"
                            f"下一步：继续写正文；可带想法重拟本批。",
                            chapter=num)
                        if g3_idea is None:
                            continue   # 回退：本批细纲已清除，重新生成
                        if g3_idea:
                            self._gate_carry_idea = g3_idea  # 注入本章正文草稿
                        break
                    if not os.path.exists(project.get_outline_path(self.proj, num)):
                        self.log("warn", f"第 {num} 章细纲仍缺失，流水线停在此处")
                        break

                self._cur_stage = st.STAGE_PROSE
                self.sig_stage.emit(st.STAGE_PROSE)
                self.sig_chapter_started.emit(num)
                # WP-27：章号上下文——本轮此后所有 LLM 调用的对话记录都带此章号
                from .. import dialogue_log
                dialogue_log.set_chapter(num)
                # 取走用户为该章登记的重写指导（消费即删，写入正文 prompt）
                state = st.load_state(self.proj)
                guidance = st.take_guidance(state, num)
                if guidance:
                    st.save_state(self.proj, state)
                    self.log("info", f"第 {num} 章应用用户重写指导：{guidance[:80]}")
                # 取走用户提交的创作想法（标记已应用，注入草稿 prompt）
                ideas = st.take_ideas(state, num)
                if ideas:
                    st.save_state(self.proj, state)
                    self.log("info", f"第 {num} 章应用用户想法 {len(ideas)} 条：{ideas[0][:60]}")
                # 决策门 G5L：草稿开始前（软门：无产物可回退，想法直接并入指导）
                g5_idea = self.gate("G5L", f"第 {num} 章上下文就绪，即将开写草稿（目标 {chapter_words} 字）",
                                    chapter=num)
                if g5_idea is None:
                    g5_idea = ""  # 软门回退按继续处理
                carry = self.consume_gate_idea()
                if carry:
                    guidance = (guidance + "\n" + carry) if guidance else carry
                if g5_idea:
                    guidance = (guidance + "\n" + g5_idea) if guidance else g5_idea
                cs = st.get_chapter_step(self.proj)
                if cs.get("num") == num and cs.get("step_done"):
                    self.log("info", f"第 {num} 章断点续跑：从「{cs.get('step_done')}」之后继续"
                                     f"（草稿与已投审校票已保留，方案 H）")
                record = stages.chapter_microcycle(self, num, guidance=guidance, ideas=ideas)
                stages.write_gen_config(self, num)   # 先落快照再发信号：闸门/信号链异常不该丢可追溯性
                self._budget_finish()   # D1：本章预算窗口收口（时长轴末次裁决）
                self.sig_chapter_done.emit(record)
                done_nums.add(num)

                state = st.load_state(self.proj)
                state["stage"] = st.STAGE_PROSE
                state["current_chapter"] = num
                st.append_history(self.proj, state, record)
                self.sig_queue.emit()
                # C35 G4 相位看门狗：正文已落库 ⇒ 记账产物必须存在（T3 记账停摆
                # 30 章零告警的翻案）——缺失 error 落账，连续 2 章 auto_pause
                self._watch_phase_products(num)
                # 决策门 G9：本章定稿完成 → 确认进下一章 / 带想法 / 回退重写本章
                self.checkpoint()
                g9_idea = self.gate("G9", f"第 {num} 章已定稿（{record.get('words', 0)} 字" +
                                    f"· 审校{record.get('review_blocking', 0)}处阻塞）",
                                    chapter=num)
                if g9_idea is not None and g9_idea:
                    self._gate_carry_idea = g9_idea  # 注入下一章
                if g9_idea is None:
                    done_nums.discard(num)  # 回退已删本章文件，循环以相同 num 重跑
                    continue
                num += 1

            if total and num > total:
                state = st.load_state(self.proj)
                state["stage"] = st.STAGE_DONE
                st.save_state(self.proj, state)
                self.sig_stage.emit(st.STAGE_DONE)
                self.log("ok", f"全书 {total} 章完本")
                self.sig_finished.emit("done")
            else:
                # WP-25：停止回执说「进度已保存」就要真的落盘——load→save 往返
                # 同时验证状态文件可解析（用户随时可续跑的承诺有据可查）
                state = st.load_state(self.proj)
                st.save_state(self.proj, state)
                self.sig_finished.emit("stopped")
        except PipelineStopped:
            self.log("info", "流水线已停止，进度已保存，可随时续跑")
            # WP-25：同上——发「进度已保存」前先完成一次真实落盘（含可解析性验证）
            state = st.load_state(self.proj)
            st.save_state(self.proj, state)
            self.sig_finished.emit("stopped")
        except StageError as e:
            self._dump_failure(e)
            self.sig_failed.emit(str(e))
        except Exception as e:
            self._dump_failure(e)
            self.sig_failed.emit(f"流水线异常: {e}")
        finally:
            llm_client.remove_call_observer(self._on_llm_call)
            self._budget_active = False

    def _dump_failure(self, error: BaseException):
        """失败现场落盘：阶段/章号/最后 prompt/日志尾部"""
        path = diagnostics.dump_failure(
            self.proj, self._cur_stage, self._cur_num,
            self.last_prompt, error, list(self._log_tail), self._cur_step)
        self.log("error", f"失败现场已保存: {path}" if path else "失败现场写入失败")
