# -*- coding: utf-8 -*-
"""流水线断点状态机：pipeline_state.json 原子读写

任何阶段失败/暂停/崩溃后，重新打开项目可从断点续跑。
"""
import json
import logging
import os
import tempfile
import threading
import time
from typing import TypedDict

STATE_FILENAME = "pipeline_state.json"

# H-4/C32：save_state 会被 GUI 线程（add_idea/set_guidance 等 Slot）与流水线
# worker 线程（checkpoint/append_history 等）并发调用。两层防护：
# ① 进程内按项目（state 实例）粒度的写锁（_project_save_lock）串行化
#    「读盘→三方合并→写临时→replace」整段——任一时刻盘上都是一份完整 JSON；
# ② save 前重读盘上现状，与调用方内存态按装载基线（PipelineState._base）做
#    三方合并（_three_way_dict）：长生成窗口（orchestrator run 主循环
#    load→…数分钟 LLM 调用…→save）里，GUI 提想法/发指导/标修复等写入
#    不再被旧快照全量回写覆盖（09-17 审查 H-4 残留主体）。
# 同键·同子键·同条目并发写 = 最后写者胜（键级契约，见 _three_way_dict 注记）；
# 跨进程并发不在此修复射程（与审查 H-4 口径一致）。
_SAVE_LOCK_TIMEOUT = 10.0  # 秒；持锁超限视为病态重入/死锁 → 降级无锁原子写 + error 告警

_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS = {}   # {normcase(绝对路径): Lock}——按项目（state 实例）懒建


def _project_save_lock(proj: str) -> threading.Lock:
    """按项目取写锁（懒建）。粒度 = 单个 pipeline_state.json（state 实例），
    不同项目互不阻塞。"""
    key = os.path.normcase(os.path.abspath(state_path(proj)))
    with _LOCKS_GUARD:
        lk = _PROJECT_LOCKS.get(key)
        if lk is None:
            lk = _PROJECT_LOCKS[key] = threading.Lock()
        return lk

# 总流水线阶段
STAGE_INIT = "init"            # 立项（仅有选题信息）
STAGE_SETTING = "setting"      # 核心设定
STAGE_OUTLINE = "outline"      # 全书大纲
STAGE_CH_OUTLINE = "ch_outline"  # 章节细纲
STAGE_PROSE = "prose"          # 正文微循环
STAGE_DONE = "done"            # 完本

STAGE_LABELS = {
    STAGE_INIT: "立项",
    STAGE_SETTING: "核心设定",
    STAGE_OUTLINE: "全书大纲",
    STAGE_CH_OUTLINE: "章节细纲",
    STAGE_PROSE: "正文写作",
    STAGE_DONE: "完本",
}
STAGE_ORDER = [STAGE_SETTING, STAGE_OUTLINE, STAGE_CH_OUTLINE, STAGE_PROSE, STAGE_DONE]

# ---------- 共写档（co-write）：六阶段状态机（与自动档键完全分离）----------
# 只写 state['cw']['stage']，绝不碰自动档 state['stage']；项目打开按 state['cw']['mode'] 判定档位粘性。
STAGE_CW_PROJECT = "cw_project"       # 创建项目（选预设/自定义主题 → 选题信息）
STAGE_CW_CORE = "cw_core"             # 核心设定（预设范例 → 讨论 → 确定=总结定稿）
STAGE_CW_OUTLINE = "cw_outline"       # 剧情总大纲（简纲+主题 → 讨论 → 确定=自动总结）
STAGE_CW_WORLDBOOK = "cw_worldbook"   # 世界书与正则（生成 → 逐条讨论 → 确定落盘）
STAGE_CW_UNIT = "cw_unit"             # 单元细纲（±10 章 → 讨论单元 → 确定单元总纲 → 章细纲滚动）
STAGE_CW_PROSE = "cw_prose"           # 正文写作（草稿 → 保存=临时 / 章节确定=终稿锁定）

CW_STAGE_ORDER = [
    STAGE_CW_PROJECT, STAGE_CW_CORE, STAGE_CW_OUTLINE,
    STAGE_CW_WORLDBOOK, STAGE_CW_UNIT, STAGE_CW_PROSE,
]

CW_STAGE_LABELS = {
    STAGE_CW_PROJECT: "创建项目",
    STAGE_CW_CORE: "核心设定",
    STAGE_CW_OUTLINE: "剧情总大纲",
    STAGE_CW_WORLDBOOK: "世界书与正则",
    STAGE_CW_UNIT: "单元细纲",
    STAGE_CW_PROSE: "正文写作",
}

# 各阶段产物落盘文件（相对项目根；cw_prose 为章节目录，动态定位）
CW_STAGE_PRODUCTS = {
    STAGE_CW_PROJECT: ["设定/选题信息.md"],
    STAGE_CW_CORE: ["设定/题材定位.md"],
    STAGE_CW_OUTLINE: ["大纲/大纲.md"],
    STAGE_CW_WORLDBOOK: ["设定/世界书.md", "设定/正则.md"],
    STAGE_CW_UNIT: ["大纲/单元总纲.md"],
    STAGE_CW_PROSE: [],
}

# 独立跳转表：cw_unit 属主裁决 —— 单元总纲唯一属主 = cw_unit，worldbook 只产两文件
CW_NEXT = {
    STAGE_CW_PROJECT: STAGE_CW_CORE,
    STAGE_CW_CORE: STAGE_CW_OUTLINE,
    STAGE_CW_OUTLINE: STAGE_CW_WORLDBOOK,
    STAGE_CW_WORLDBOOK: STAGE_CW_UNIT,
    STAGE_CW_UNIT: STAGE_CW_PROSE,
    STAGE_CW_PROSE: STAGE_CW_PROSE,   # 终态：章节确定=锁定，不前进
}

CW_PREV = {v: k for k, v in CW_NEXT.items() if k != STAGE_CW_PROSE}

# 打回级联矩阵：{打回阶段: 需失效（归档后删除）的产物模式列表}
# 模式支持精确相对路径或以 ".md" 结尾的前缀扫描（如 细纲_）
CW_ROLLBACK_CASCADE = {
    STAGE_CW_CORE: [
        "大纲/大纲.md", "细纲_", "设定/世界书.md", "设定/正则.md", "大纲/单元总纲.md",
    ],
    STAGE_CW_OUTLINE: ["细纲_", "大纲/单元总纲.md"],
    STAGE_CW_WORLDBOOK: ["细纲_", "大纲/单元总纲.md"],
    STAGE_CW_UNIT: ["细纲_"],
    STAGE_CW_PROSE: [],   # M4：重写本章（锁定语义）
}

# 可回看世界书回边（reopen 软切）的阶段
CW_REOPEN_SOURCES = [STAGE_CW_UNIT, STAGE_CW_PROSE]

# 章节微循环步骤
STEP_ASSEMBLE = "assemble"
STEP_DRAFT = "draft"
STEP_ENRICH = "enrich"
STEP_SCAN = "scan"
STEP_DESLOP = "deslop"
STEP_REVIEW = "review"
STEP_FINALIZE = "finalize"

STEP_LABELS = {
    STEP_ASSEMBLE: "上下文组装",
    STEP_DRAFT: "草稿生成",
    STEP_ENRICH: "字数扩写",
    STEP_SCAN: "AI 味扫描",
    STEP_DESLOP: "去味改写",
    STEP_REVIEW: "审校",
    STEP_FINALIZE: "定稿落库",
}
STEP_ORDER = [STEP_ASSEMBLE, STEP_DRAFT, STEP_SCAN, STEP_DESLOP, STEP_REVIEW, STEP_FINALIZE]

# ---- v2：6 阶段特化提示词键（与 app/presets/__init__.py STAGE_HINT_KEYS 对齐）----
# 顺序固定：core_setting → outline → unit_outline → prose → worldbook → review
STAGE_KEYS = (
    "core_setting",  # 核心设定阶段
    "outline",        # 大纲阶段
    "unit_outline",   # 细纲阶段
    "prose",          # 正文阶段（文风锚）
    "worldbook",      # 世界书阶段
    "review",         # 审校阶段
)
STAGE_KEY_SET = frozenset(STAGE_KEYS)


# ---- v2 6 维最终审核（review_findings 持久化）----

def save_review_findings(proj: str, state: dict, num: int, verdict: str,
                         items: list, blocking: list = None, advisory: list = None):
    """v2 6 维审校结果落盘到 state['review_findings'][num]。

    Args:
        num: 章节号
        verdict: PASS / PASS_WITH_NOTES / REJECT / REJECT-HARD
        items: 解析 FINAL_REVIEW_PROMPT 输出的 issue 列表 [{dim, level, text, quote, root_layer}, ...]
        blocking: 阻断级（兼容 v1 解析）
        advisory: 建议级（兼容 v1 解析）
    """
    import datetime
    rf = state.setdefault("review_findings", {})
    rf[str(num)] = {
        "verdict": verdict,
        "items": items or [],
        "blocking": blocking or [],
        "advisory": advisory or [],
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(proj, state)


def load_review_findings(state: dict, num: int) -> dict:
    """读取某章 v2 6 维审校结果（缺则返回空 dict）"""
    rf = state.get("review_findings") or {}
    return rf.get(str(num), {})


def append_review_chain(proj: str, state: dict, num: int, issues: list,
                        reworks: list, verdict: str, round_no: int):
    """v3 反馈闭环：记录每轮 issue/重做/裁决（保留最近 3 轮历史）。"""
    import datetime
    chain = state.setdefault("review_chain", {})
    ch = chain.setdefault(str(num), {
        "issues": [],
        "reworks": [],
        "verdict_history": [],
        "rounds": 0,
    })
    ch["issues"] = (ch.get("issues") or []) + list(issues or [])
    ch["reworks"] = (ch.get("reworks") or []) + list(reworks or [])
    ch["verdict_history"] = (ch.get("verdict_history") or []) + [
        {"verdict": verdict, "round": round_no,
         "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ]
    ch["rounds"] = (ch.get("rounds", 0)) + 1
    save_state(proj, state)


def clear_review_chain(proj: str, state: dict, num: int):
    """chapter_done 时清空（防 50 章长篇 state 膨胀）"""
    chain = state.get("review_chain") or {}
    if str(num) in chain:
        chain.pop(str(num), None)
        state["review_chain"] = chain
        save_state(proj, state)


def mark_chapter_need_human(proj: str, state: dict, num: int):
    """标记某章需人工介入（3 次 REJECT 不收敛时调用）"""
    import datetime
    nhh = state.setdefault("chapter_need_human", {})
    nhh[str(num)] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(proj, state)


def is_chapter_need_human(state: dict, num: int) -> bool:
    """查询某章是否已标 human（流水线跳过）"""
    nhh = state.get("chapter_need_human") or {}
    return str(num) in nhh


def _chapter_prose_path(proj: str, num: int):
    from .. import project
    for n, _name, p in project.list_chapters(proj):
        if n == num:
            return p
    return None


def _parse_ts(ts: str):
    import datetime
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _now_str() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_review_stale(proj: str, state: dict, num: int) -> bool:
    """审校结论陈旧判定：正文文件在结论落盘之后被改过（手改使结论失效）。

    旧数据无 findings/无 ts/无正文文件一律不判陈旧（安全迁移，不误报）。
    """
    ts = (load_review_findings(state, num) or {}).get("ts")
    reviewed = _parse_ts(ts) if ts else None
    if reviewed is None:
        return False
    try:
        path = _chapter_prose_path(proj, num)
        if not path or not os.path.exists(path):
            return False
        return os.path.getmtime(path) > reviewed.timestamp() + 1.0   # 秒级截断容差
    except Exception:
        return False


def mark_backflowed(proj: str, state: dict, num: int, report: str = ""):
    """登记某章剧情反哺已完成（触发点去重用）"""
    bf = state.setdefault("backflowed", {})
    bf[str(num)] = {"ts": _now_str(), "report": report}
    save_state(proj, state)


def backflow_is_fresh(proj: str, state: dict, num: int) -> bool:
    """反哺新鲜：已登记且正文在登记之后未再改动 → 无需重跑"""
    rec = (state.get("backflowed") or {}).get(str(num))
    done = _parse_ts((rec or {}).get("ts", "")) if rec else None
    if done is None:
        return False
    try:
        path = _chapter_prose_path(proj, num)
        if not path or not os.path.exists(path):
            return False
        return os.path.getmtime(path) <= done.timestamp()
    except Exception:
        return False


def record_forced_lock(proj: str, state: dict, num: int, reason: str = ""):
    """强锁审计：字数未达标仍被用户强制锁定终稿时留痕"""
    fl = state.setdefault("forced_locks", {})
    fl[str(num)] = {"ts": _now_str(), "reason": reason}
    save_state(proj, state)

# ---- T3.2 类型加固：运行时仍是普通 dict（JSON 序列化兼容），TypedDict 仅作静态标注与校验依据 ----
class CWStateTD(TypedDict, total=False):
    """state['cw'] 子树键型（cw_defaults 为唯一默认源；未知键允许存在）"""
    mode: str            # auto=自动档 / cw=共写档（项目级粘性）
    stage: str           # 当前共写阶段
    preset: str
    transcript: dict     # {阶段key: [{role, text, nums?}]}（nums=这条回执对应的细纲章号）
    handoff: dict        # {阶段key: 交接小节}
    reopening: str
    locked: dict
    unit: dict
    supervised: dict
    report: dict
    last_outline_batch: list   # 最近一批细纲的章号：编辑器跟随最新一批


class PipelineStateTD(TypedDict, total=False):
    """pipeline_state.json 顶层键型（GUI/TUI 共享契约）"""
    stage: str
    current_chapter: int
    chapter_step: str
    total_chapters: int
    paused: bool
    history: list
    pending_guidance: dict
    pending_ideas: list
    review_findings: dict
    review_chain: dict
    chapter_need_human: dict
    anomalies: list
    cw: CWStateTD


DEFAULT_STATE: PipelineStateTD = {
    "stage": STAGE_INIT,
    "current_chapter": 0,       # 最近定稿的章号
    "chapter_step": "",         # 当前章执行到微循环哪一步（断点用）
    "total_chapters": 0,        # 计划总章数（0=不限）
    "paused": False,
    "history": [],              # [{num,title,words,deslop_blocking,deslop_advisory,status,ts}]
    "pending_guidance": {},     # {章号: 重写指导语}：用户"带指导重写"时暂存，续跑时消费
    "pending_ideas": [],        # 用户创作想法队列（写作中随时提交，下一章草稿注入）
    "review_findings": {},      # {章号: [{verdict, items, ts, blocking, advisory, ...}]} v2 6 维审校结果
    "review_chain": {},         # {章号: {issues, reworks, rounds, verdict_history}} v3 反馈闭环状态
    "chapter_need_human": {},   # {章号: ts} 3 次 REJECT 不收敛时标 human，跳过本轮继续
    # C35 G5：台账/看门狗异常告警（[{ts, rule, ch, level, msg, ...}]，尾部保留 500 条）。
    # 写入方=app.usage.report_anomaly（G5 规则命中）与 orchestrator._watch_phase_products
    # （G4 相位看门狗）；UI 常驻横幅与跑后汇总消费。
    "anomalies": [],            # [{ts, rule, ch, level, msg, ...}]
}


# 已知键的运行时类型（校验依据；未知键一律保留不拒绝——真实存档含 genre_preset 等扩展键）
_STATE_KEY_TYPES = {
    "stage": str,
    "current_chapter": int,
    "chapter_step": str,
    "total_chapters": int,
    "paused": bool,
    "history": list,
    "pending_guidance": dict,
    "pending_ideas": list,
    "review_findings": dict,
    "review_chain": dict,
    "chapter_need_human": dict,
    "anomalies": list,
    "backflowed": dict,
    "forced_locks": dict,
    "cw": dict,
}
_CW_KEY_TYPES = {
    "mode": str, "stage": str, "preset": str, "transcript": dict,
    "handoff": dict, "reopening": str, "locked": dict, "unit": dict,
    "supervised": dict, "report": dict,
}
_EMPTY_BY_TYPE = {str: "", int: 0, bool: False, list: [], dict: {}}


class StateValidationError(ValueError):
    """pipeline_state.json 已知键类型损坏——早报错，防半损坏状态流入写入路径"""


def _type_ok(v, typ) -> bool:
    if typ is int:
        return isinstance(v, int) and not isinstance(v, bool)  # bool 是 int 子类，需特判
    return isinstance(v, typ)


def _null_default(k: str):
    """旧存档显式 null 的就地修复值"""
    if k == "cw":
        return {}
    d = DEFAULT_STATE.get(k)
    return d if d is not None else _EMPTY_BY_TYPE[_STATE_KEY_TYPES[k]]


def validate_state(state: dict) -> dict:
    """最小键校验：已知键类型必须正确；None 修复为默认空值；未知键保留。
    load/save 入口调用，损坏抛 StateValidationError。"""
    for k, typ in _STATE_KEY_TYPES.items():
        if k not in state:
            continue
        if state[k] is None:
            state[k] = _null_default(k)
            continue
        if not _type_ok(state[k], typ):
            raise StateValidationError(
                f"pipeline_state 键 {k!r} 类型损坏：期望 {typ.__name__}，"
                f"实际 {type(state[k]).__name__}")
    cw = state.get("cw")
    if isinstance(cw, dict):
        for k, typ in _CW_KEY_TYPES.items():
            if k not in cw or cw[k] is None:
                continue
            if not _type_ok(cw[k], typ):
                raise StateValidationError(
                    f"pipeline_state 键 cw['{k}'] 类型损坏：期望 {typ.__name__}，"
                    f"实际 {type(cw[k]).__name__}")
    return state


def cw_defaults() -> CWStateTD:
    """共写档状态结构（state['cw']）：档位粘性 + 六阶段机 + 转写/交接块/锁定"""
    return {
        "mode": "auto",              # auto=自动档 / cw=共写档（项目级粘性）
        "stage": STAGE_CW_PROJECT,   # 当前共写阶段
        "preset": "",                # cw_preset：共写档选用的题材预设
        "transcript": {},            # {阶段key: [{role: user/agent, text}]} 对话转写
        "handoff": {},               # {阶段key: "→ 下阶段交接"小节（≤800字）} 唯一属主
        "reopening": "",             # 非空 = 回看回边中（目标阶段key，重确定后返回原阶段）
        "locked": {},                # {章号: 锁定时间戳} 终稿锁定（M4 落 annotations，此处留痕）
        "unit": {},                  # 单元信息（M3）
        "supervised": {},            # {章号: 主 Agent 衔接比对时间戳}（M5 触发点①）
        "report": {},                # {ts, num, text} 主 Agent 报告（M5 报告区）
        "stage_mode": {},            # {阶段key: discuss/compose} 回应模式记忆（方案 A）
    }


def raw_cw_mode(proj: str) -> str:
    """读 state.cw.mode 的**落盘原值**——不经 ensure_cw 填默认。

    B-1/R17：新项目创建时显式写入出厂档位；「从未表态」返回空串，
    调用方据此保持升级前行为（自动档），绝不静默回填。"""
    try:
        with open(state_path(proj), "r", encoding="utf-8") as f:
            cw = (json.load(f) or {}).get("cw") or {}
        m = cw.get("mode")
        return str(m) if m else ""
    except Exception:
        return ""


def ensure_cw(state: dict) -> dict:
    """补齐 state['cw'] 缺省字段（旧项目无此键时使用）"""
    cw = state.get("cw")
    if not isinstance(cw, dict):
        cw = {}
    merged = cw_defaults()
    merged.update(cw)
    state["cw"] = merged
    return merged


def set_guidance(proj: str, state: dict, num: int, text: str):
    """登记某章的重写指导（写入 state 并落盘）"""
    # H-4：键统一 str——旧实现 set 用 int、take 用 str(num)，JSON 往返后
    # int 键恒变 str，登记的指导永远取不回（静默丢失）
    state.setdefault("pending_guidance", {})[str(num)] = text
    save_state(proj, state)


def take_guidance(state: dict, num: int) -> str:
    """取走某章的待用指导（消费即删除）"""
    pg = state.get("pending_guidance") or {}
    # H-4：str 键为主，兼容内存中尚存的 int 键（旧版本登记、未经落盘往返）
    if str(num) in pg:
        return pg.pop(str(num))
    return pg.pop(num, "") if isinstance(num, int) else ""


def add_idea(proj: str, state: dict, text: str, scope: str = "next"):
    """提交一条创作想法（结构化：状态/注入范围/时间），下一章或指定章草稿消费

    scope: "next"=下一章 | "通用"=通用想法 | 数字字符串=指定第N章
    兼容旧格式（纯字符串）——读取时统一转结构化。
    """
    text = (text or "").strip()
    if not text:
        return False
    import datetime
    state.setdefault("pending_ideas", []).append({
        "id": f"idea_{int(time.time() * 1000) % 100000000}_{len(state['pending_ideas'])}",
        "text": text,
        "status": "pending",            # pending / applied
        "scope": scope,
        "ts": datetime.datetime.now().strftime("%m-%d %H:%M"),
    })
    save_state(proj, state)
    return True


def norm_ideas(state: dict) -> list:
    """想法列表规范化：旧格式纯字符串 → 结构化（scope=next）"""
    result = []
    for it in state.get("pending_ideas") or []:
        if isinstance(it, str):
            it = {"id": f"legacy_{len(result)}", "text": it, "status": "pending",
                  "scope": "next", "ts": ""}
        if it.get("text"):
            result.append(it)
    return result


def take_ideas(state: dict, num: int = 0) -> list:
    """取走本章待消费想法文本，按 scope 注入策略（T4.2 想法沉淀）：
    - next / ==num：一次性，take 后标记 applied
    - 通用：跨章持续注入——每章草稿都带上且不自动标记 applied
      （停止注入 = 面板「标记已应用」/删除，见 plan_step_gates_v1 §8）
    """
    ideas = norm_ideas(state)
    taken = []
    for it in ideas:
        if it.get("status") != "pending":
            continue
        scope = str(it.get("scope", "next"))
        if scope == "通用":
            taken.append(it["text"])          # 持续注入：不改状态
        elif scope == "next" or (num and scope == str(num)):
            taken.append(it["text"])
            it["status"] = "applied"
    state["pending_ideas"] = ideas
    return taken


def pending_idea_texts(state: dict) -> list:
    return [it["text"] for it in norm_ideas(state) if it.get("status") == "pending"]


def state_path(proj: str) -> str:
    return os.path.join(proj, STATE_FILENAME)


# ---------- H-4/C32：跨线程 load→改→save 丢失更新防护 ----------

_MISSING = object()   # 哨兵：区分「键缺失」与「值为 None」


class PipelineState(dict):
    """load_state 的返回容器（dict 子类）。

    携带 _base = 装载时刻的深拷贝基线；save_state 据此做三方合并
    （基线/内存/盘上），长生成窗口内其他线程写入的键不被本线程全量回写覆盖。
    对外仍是普通 dict：isinstance(state, dict) 成立，取值/赋值/序列化行为不变；
    调用方自建的裸 dict 无基线 → save 走旧整写语义（「我拥有全部状态」）。
    """
    __slots__ = ("_base",)


def _read_disk_state(path: str):
    """读盘上当前状态（不加锁：os.replace 原子性保证读到完整 JSON）。
    文件缺失/解析失败返回 None → 调用方按旧语义整写（损坏留证已在 load 侧 A-8）。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _list_item_key(item):
    """列表条目的身份键：history 用 num、pending_ideas 用 id；不可识别返回 None"""
    if isinstance(item, dict):
        if "num" in item:
            return ("num", item["num"])
        if "id" in item:
            return ("id", item["id"])
    return None


def _merge_list_by_id(base, mem, disk):
    """列表条目粒度三方合并（history / pending_ideas 等带身份键的 dict 条目表）：
    - 本线程未动的条目（== 基线）：以盘上为准（他线程改的字段生效，如 needs_fix→pass）
    - 本线程改过/新增的条目：内存为准（worker 定稿新记录、想法标 applied）
    - 盘上新增条目（他线程写入，如 GUI 窗口内提交的想法）：追加尾部
    条目顺序以内存为骨架（history 顺序由 append_history 负责排序）。"""
    def keyed(seq):
        return {_list_item_key(x): x for x in seq if _list_item_key(x) is not None}
    b_by, d_by = keyed(base), keyed(disk)
    out = []
    for x in mem:
        k = _list_item_key(x)
        if k is None:
            out.append(x)                      # 无身份条目：内存为准
            continue
        bx = b_by.get(k, _MISSING)
        dx = d_by.get(k, _MISSING)
        if bx is not _MISSING and x == bx:
            if dx is not _MISSING:
                out.append(dx)                 # 未动 → 盘上为准（含他线程的字段修改）
            # 盘上也没有 → 他线程删除了该条目 → 尊重删除
        else:
            out.append(x)                      # 改过/新增 → 内存为准
    known = set(b_by) | {_list_item_key(x) for x in mem if _list_item_key(x) is not None}
    out.extend(y for k2, y in d_by.items() if k2 not in known)
    return out


def _three_way_dict(base, mem, disk):
    """键粒度三方合并（对 dict 键可递归下沉到子键）：返回新 dict，不改任何入参。
    - 键被本线程删除：保持删除（carry_idea 消费场景）
    - 键本线程未动（== 基线）：盘上为准（含他线程改值/删除——长窗口不回滚别人）
    - 键本线程新增或独改：内存为准
    - 双方都改：dict 键下沉子键再三方；带身份键的条目表按条目三方；
      其余（标量/结构不符）内存为准——最后写者胜。"""
    out = {}
    for k in set(base) | set(mem) | set(disk):
        b = base.get(k, _MISSING)
        m = mem.get(k, _MISSING)
        d = disk.get(k, _MISSING)
        if m is _MISSING:
            if b is _MISSING and d is not _MISSING:
                out[k] = d        # 本线程不认识的盘上新键（他线程刚写入）→ 收下
            continue              # 其余：本线程删除 / 双方皆无 → 保持删除
        if b is not _MISSING and m == b:
            if d is not _MISSING:
                out[k] = d        # 本线程未动 → 盘上为准
            continue              # 盘上也没有 → 他线程删除 → 尊重删除
        if d is _MISSING or b is _MISSING or d == b:
            out[k] = m            # 盘上未动 / 本线程新增键 → 内存为准
            continue
        # 双方都改 → 分型合并
        if isinstance(b, dict) and isinstance(m, dict) and isinstance(d, dict):
            out[k] = _three_way_dict(b, m, d)
        elif (isinstance(b, list) and isinstance(m, list) and isinstance(d, list)
              and all(_list_item_key(x) is not None for x in b + m + d)):
            out[k] = _merge_list_by_id(b, m, d)
        else:
            out[k] = m            # 兜底：内存为准（同键并发写最后写者胜）
    return out


def load_state(proj: str) -> "PipelineState":
    path = state_path(proj)
    state = PipelineState(json.loads(json.dumps(DEFAULT_STATE)))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                state[k] = v
        except Exception as e:
            # A-8/C-3：状态文件损坏必须**保现场**——旧实现直接 pass，下次
            # save_state 会把唯一现场覆盖掉（实测截断 88 章存档永久丢失）。
            # 抄 volume_session._keep_aside：坏文件追加式留证 + 大声提示
            import datetime
            try:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                with open(path, "rb") as rf:
                    raw = rf.read()
                with open(f"{path}.corrupt-{ts}", "ab") as af:
                    af.write((f"==== corrupt @ {ts}: {e} ====\n").encode("utf-8"))
                    af.write(raw)
                logging.getLogger("qianbi.state").error(
                    "state.json 解析失败（%s），坏文件已留证 %s.corrupt-%s；"
                    "本次按默认状态继续——确认无误后可参照留证手工恢复", e, path, ts)
            except Exception:  # noqa: BLE001
                logging.getLogger("qianbi.state").error("state.json 损坏且留证失败：%s", e)
    validate_state(state)   # T3.2：损坏早报错，不静默降级
    ensure_cw(state)
    # H-4/C32：装载基线快照（深拷贝）——save_state 据此识别「本线程改过没有」，
    # 未动的键以盘上为准，长生成窗口内其他线程的写入不被全量回写覆盖。
    state._base = json.loads(json.dumps(state))
    return state


def _atomic_write_json(path: str, data: dict):
    """写临时文件 + os.replace 原子替换，防中途崩溃损坏状态。
    os.replace 在 Windows 上会被杀软/索引器的瞬时文件锁拒绝（真机 WinError 5），
    重试 3 次退避后再放弃。调用方负责持项目写锁。"""
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        last_err = None
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                last_err = None
                break
            except PermissionError as e:   # 瞬时文件锁：退避重试
                last_err = e
                time.sleep(0.2 * (attempt + 1))
        if last_err is not None:
            raise last_err
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def save_state(proj: str, state: dict):
    """原子写入 + 跨线程三方合并（H-4/C32）。

    写前最小键校验（T3.2）；「读盘→合并→写临时→replace」整段在按项目粒度的
    进程内写锁（_project_save_lock）内串行。调用方持 load_state 旧快照时：
    本线程改过的键以内存为准，未动的键以盘上为准——长生成窗口（orchestrator
    run 主循环）里 GUI 提想法/发指导/标修复的落盘不被旧快照覆盖。
    无基线（裸 dict）或盘上缺失/损坏 → 旧整写语义。锁等待超过
    _SAVE_LOCK_TIMEOUT 视为病态重入/死锁：降级无锁原子写（os.replace 原子性
    仍在，无截断现场）并 error 告警，绝不永久挂死。
    """
    validate_state(state)
    path = state_path(proj)
    base = getattr(state, "_base", None)
    lk = _project_save_lock(proj)
    have_lock = lk.acquire(timeout=_SAVE_LOCK_TIMEOUT)
    if not have_lock:
        logging.getLogger("qianbi.state").error(
            "save_state 项目写锁等待超时（%.1fs，%s）——疑似重入/死锁，"
            "降级为无锁原子写", _SAVE_LOCK_TIMEOUT, path)
    try:
        disk = _read_disk_state(path)
        if base is None or disk is None:
            merged = dict(state)      # 裸 dict / 盘上缺失或损坏：旧语义整写
        else:
            merged = _three_way_dict(base, state, disk)
        _atomic_write_json(path, merged)
    finally:
        if have_lock:
            lk.release()


def append_history(proj: str, state: dict, record: dict):
    import datetime
    record = dict(record)
    record["ts"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["history"] = [h for h in state.get("history", []) if h.get("num") != record.get("num")]
    state["history"].append(record)
    state["history"].sort(key=lambda h: h.get("num", 0))
    save_state(proj, state)


def update_history_status(proj: str, state: dict, num: int, status: str) -> bool:
    """就地更新已有 history 记录的 status（如待修章修复后 needs_fix→pass）。

    记录不存在时不动 state，返回 False。
    """
    for h in state.get("history", []):
        if h.get("num") == num:
            if h.get("status") != status:
                h["status"] = status
                save_state(proj, state)
            return True
    return False


# ---------- 章内断点（方案 H）：草稿即文件，步骤级 checkpoint ----------
# chapter_step 在 _STATE_KEY_TYPES 里声明为 str（键早已预留）：存 JSON 串，尊重既有契约

def save_chapter_step(proj: str, num: int, step_done: str,
                      draft_path: str = "", votes: list = None,
                      outline_fp: str = ""):
    """记录章内微循环最后完成的步骤（草稿/扩写/扫描/去味/审校/定稿）。

    停在任何位置再重启，恢复语义 = 重跑被打断的那一步，之前完成的步骤
    （草稿文件、已投的审校票）原样保留——不再「停一次全章白写」。
    outline_fp：细纲内容指纹。细纲重生成后指纹变化，旧断点作废——
    否则会拿旧断点恢复出新细纲根本没喂过的旧草稿（R4 实测事故）。
    """
    state = load_state(proj)
    state["chapter_step"] = json.dumps(
        {"num": int(num), "step_done": step_done, "draft_path": draft_path,
         "votes": votes or [], "outline_fp": outline_fp, "ts": time.time()},
        ensure_ascii=False)
    save_state(proj, state)


def get_chapter_step(proj: str) -> dict:
    raw = load_state(proj).get("chapter_step") or ""
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def clear_chapter_step(proj: str, num: int = None):
    """清除章内断点。num 给定时只清**属于该章**的断点（L1-02：agent 重写第 12 章
    不得动第 30 章的在途断点——旧实现无条件清，跨章误清=毁断点）；num=None 保持
    旧无差别语义（仅限定稿收尾自己清自己）。"""
    state = load_state(proj)
    raw = state.get("chapter_step")
    if not raw:
        return
    if num is not None:
        try:
            if json.loads(raw).get("num") != int(num):
                return          # 断点属于别的章：不动
        except (ValueError, TypeError):
            pass
    state["chapter_step"] = ""
    save_state(proj, state)
