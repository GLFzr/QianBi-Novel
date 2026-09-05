# -*- coding: utf-8 -*-
"""流水线断点状态机：pipeline_state.json 原子读写

任何阶段失败/暂停/崩溃后，重新打开项目可从断点续跑。
"""
import json
import os
import tempfile
import time
from typing import TypedDict

STATE_FILENAME = "pipeline_state.json"

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
    state.setdefault("pending_guidance", {})[num] = text
    save_state(proj, state)


def take_guidance(state: dict, num: int) -> str:
    """取走某章的待用指导（消费即删除）"""
    pg = state.get("pending_guidance") or {}
    return pg.pop(str(num), "")


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


def load_state(proj: str) -> dict:
    path = state_path(proj)
    state = json.loads(json.dumps(DEFAULT_STATE))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                state[k] = v
        except Exception:
            pass
    validate_state(state)   # T3.2：损坏早报错，不静默降级
    ensure_cw(state)
    return state


def save_state(proj: str, state: dict):
    """原子写入：先临时文件再替换，防中途崩溃损坏状态；写前最小键校验（T3.2）。
    os.replace 在 Windows 上会被杀软/索引器的瞬时文件锁拒绝（真机 WinError 5），
    重试 3 次退避后再放弃。"""
    validate_state(state)
    path = state_path(proj)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=proj)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
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


def clear_chapter_step(proj: str):
    state = load_state(proj)
    if state.get("chapter_step"):
        state["chapter_step"] = ""
        save_state(proj, state)
