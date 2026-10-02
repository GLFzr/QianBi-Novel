# -*- coding: utf-8 -*-
"""长程历史压缩：装配式「卷终交接块」（零 LLM 调用·零网络）

设计依据（权威口径在文档里，本模块只是实现契约）：
《长程压缩与cheap区间_v1.md》§4.2 分层 / §4.3 接力压缩协议 / §4.3.1 五条保险丝 /
§6.2 内置化（触发器与产物落点）/ §6.3 费用最小化（组装式压缩）。

**装配式（§6.3）**：流水线每章已经在生产压缩所需的一切原料——章正文、
章节摘要链（追踪/章节摘要.md）、全局摘要（追踪/全局摘要.md）、角色状态/时间线/
伏笔台账（tracking 每章更新）、连续性台账.json（清算每章更新）。交接块 = 这些
既有产物的确定性装配：

    交接块 = 近 2 章结尾原文（800+400 字，逐字） + 近 3 章 chapter_summary
             + 台账快照（经常驻去重） + 全局摘要（经常驻去重）

零 prompt 构造、零 API 调用，压缩操作自身费用精确为 0。

**五条保险丝（§4.3.1，逐条对应实现，全 fail-open）**：
  ① shrink 校验（`_shrink_ok`）：交接块必须显著小于它替换掉的整卷逐字历史，
     否则拒绝压缩——返回「未压缩」而不是把块裁小（不静默降级）；
  ② 近程尾巴逐字保留（`near_endings` + `_verbatim_ok`）：装配后逐条校验原文仍在
     块内一字未改，丢了就拒绝；
  ③ 不复述常驻注入（`dedup_resident`）：与 system（project_header）/章头
     （chapter_header）逐行比对，已注入的内容从块里剔除——重复注入会引发行为
     异常（DSH issue #5766 教训），宁可少说不可重说；
  ④ token 计量走真实 usage（`session_input_estimate`）：会话输入规模取 usage.jsonl
     的**最近一笔**实测 prompt_tokens（API 真值，且压缩重置后会立刻回落——整跑最大
     值停在压缩前规模，用它当口径会逐章重复点火）；无实测才退到仓库既有中文口径
     （0.6 token/汉字，同 scripts/header_audit.py），**不用** DSH 自认低估 CJK 的
     4 字符/token 启发式；
  ⑤ 精确锚点留在台账（`ledger_snapshot`）：块只承载叙事记忆，数值/日期/名单/
     物证位置一律指向台账文件（「以台账为准」），块内不复述；
  ⑥ 因果断言（WA5/B1+B8，FlawedFictions 缺口）：装配前从被替换历史提取「因果链
     断言清单」（因果连接词句对 / 未回收伏笔承诺 / 事件钩应答标记三源，纯启发式），
     装配后对断言逐条核对语义在场（每个锚词槽任一别名可检索，归一化复用
     fact_ledger.normalize 的 C42 口径）；未在场先降级「保链压缩」（失败句原文
     保底附加成第五节），追加后仍违反保险丝①才整笔拒绝（fail-open）——
     保险丝②保近程尾巴，这根保跨章因果债务（研究实证：摘要丢因果链是
     连续性错误率 +50% 的主因，arXiv 2504.11900）。

**flag 纪律（硬性）**：`writing.compaction` 默认关。接线契约两条，缺一即破 A/B 口径：
  - 关闭时 stages 侧**不得触达**本模块（旗标读数放在调用点，`import` 也要放在旗标
    之后）——请求体与改造前逐字节一致；
  - 即便被误调用，`opening_block`/`should_compact`/`build_handoff_block` 也一律返回
    「不介入」，`compose_open_turn` 的输出与 volume_session 现状**逐字节一致**
    （本模块对请求体的贡献为 0 字节，可由 sha256("") 直接验证）。

产物（§6.2）：`追踪/交接块_卷N.md`（人读）+ `.json`（机读，断点续跑与
volume_session 的 load 链路用）。文本不含时间戳——同一份盘态两次装配逐字节一致，
sha256 稳定可锁。

本模块是库：无 CLI、无 UI、不注册进任何默认配置。
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from .. import project
from . import memory

# ---- 旗标与阈值（§6.2；0.24.0 Q1-a 质量标定）----
FLAG_KEY = "compaction"                       # cfg["writing"]["compaction"]，默认开
THRESHOLD_KEY = "compaction_token_threshold"  # 触发器②的阈值覆盖位
# 0.24.0 质量标定：旧 800k 是按**成本**标定的（deepseek 全价时代的省钱闸）——三测
# 取证 E1-E4 证明质量劣化区在 100k+（192k 窗口模型单发 157k 时盲评 3.8，5k 时 7.9），
# 全程发生在旧阈值之下，护栏形同虚设。新默认 48k ≈ 192k 窗口的 25%（小窗模型
# 可用 compaction_token_threshold 覆盖）。828k→48k 之间的会话质量代价见
# docs/0.24.0_质量全量提升计划.md §一 P0-1。
DEFAULT_TOKEN_THRESHOLD = 48_000

# ---- 装配窗口（§4.3 项 2 / §6.3）----
NEAR_TAIL_CHARS = (800, 400)   # 最近章末 800 字 + 次近章末 400 字（逐字保留）
SUMMARY_WINDOW = 3             # 近 3 章 chapter_summary
SHRINK_MAX_RATIO = 0.5         # 保险丝①：块/被替换历史 ≤ 0.5 才算「显著更小」
LEDGER_BUDGET_CHARS = 2000     # 台账快照单节上限（与 chapter_header 的截断同量级）
MAX_HOME_UPWARD = 5            # 用量落点上溯层数上限（项目→…→假 home；防翻到别书/用户真实数据）

# ---- 保险丝④的计量口径 ----
# B2d 拆环：han_tokens 口径下沉 app/core/text_metrics.py（volume_session 反向引用
# 曾成环）；此处同名 re-export 保持本模块与外部消费方（stages/tests）原样。
from .text_metrics import TOKENS_PER_HAN, _HAN_RE, han_tokens  # noqa: E402,F401

# ---- 保险丝⑥（WA5）的在场判定口径 ----
# 归一化复用 C42 fact_ledger.normalize（NFKC + 去空白 + 剥引号/破折号）：
# 同义改写/全半角/引号差在断言判定里仍算「语义在场」，与事实账本锚定同口径。
from .fact_ledger import normalize  # noqa: E402

# 卷会话相位（这些相位的单笔 in 才是「会话输入有多长」的真值来源）
_SESSION_PHASES = ("prose", "enrich", "trim", "deslop", "review", "review_fix",
                   "root_cause", "tracking", "chapter_summary", "global_summary")

# 台账原料：(块内节名, project.get_tracking_path 的 name)
_LEDGER_ITEMS = (("角色状态", "角色状态"), ("时间线", "时间线"), ("伏笔", "伏笔"))

ARTIFACT_KIND = "qianbi-volume-handoff"
ARTIFACT_VERSION = 1

# 会话栈文件名：卷N_messages.jsonl（原始）/ 卷N_cK_messages.jsonl（第 K 代压缩后新栈）
_STACK_FILE_RE = re.compile(r"^卷(\d+)(?:_c(\d+))?_messages\.jsonl$")

_MID_VOLUME_MARK = "【新章开幕：以下为本章共享上下文与写作指令，本章正文以本次回复为准】"


# ==================== 结果对象 ====================

@dataclass(frozen=True)
class Trigger:
    """§6.2 触发器读数：reason 为空 = 不压缩。"""
    reason: str = ""          # "" | volume_boundary | input_threshold | manual
    detail: str = ""

    @property
    def fire(self) -> bool:
        return bool(self.reason)


@dataclass(frozen=True)
class HandoffResult:
    """一次装配的结果。任何一条保险丝不过 → ok=False / text="" / 不落盘（fail-open）。"""
    ok: bool
    text: str = ""                    # 交接块全文（拒绝时为空串）
    tokens: int = 0                   # 块自身规模（保险丝④口径）
    replaced_tokens: int = 0          # 块替换掉的整卷逐字历史规模（保险丝①基准）
    shrunk: bool = False              # 保险丝①是否通过
    meter: str = "han-caliber"        # token 计量口径（审计用）
    trigger: str = ""                 # volume_boundary / input_threshold / manual
    reason: str = ""                  # 拒绝原因（ok=False 时非空）
    flag_on: bool = True
    volume: int = 1
    from_chapter: int = 0
    to_chapter: int = 0
    artifacts: tuple = ()             # 已落盘产物路径（write=False 时为空）
    sections: dict = field(default_factory=dict)   # 机读分节（json 产物的内容）
    causal_checked: int = 0           # 保险丝⑥：断言清单核对条数（0=无断言直通）
    causal_failed: int = 0            # 首轮未在场断言数（degrade 后由降级兜住）
    degraded: bool = False            # 是否走了「保链压缩」降级（失败句原文保底附加）

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def shrink_ratio(self) -> float:
        if self.replaced_tokens <= 0:
            return 1.0
        return round(self.tokens / self.replaced_tokens, 4)


@dataclass(frozen=True)
class OpeningBlock:
    """新卷开幕块的确定性产物：text + 稳定 sha256。contributed=False ⇒ 零贡献。"""
    text: str = ""
    tokens: int = 0
    contributed: bool = False
    reason: str = ""
    replaced_tokens: int = 0      # 块顶替掉的逐字历史规模（压缩的成绩单，供接线与晨报）
    shrink_ratio: float = 1.0

    @property
    def sha256(self) -> str:
        """开幕块文本的稳定指纹。不介入时 text 为空串 → 返回空串的 sha256，
        即「本模块对请求体贡献 0 字节」的可验证证据。"""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


# ==================== 保险丝④：token 计量 ====================
# han_tokens / TOKENS_PER_HAN / _HAN_RE 已下沉 app/core/text_metrics.py（见头部 re-export）。


def usage_path(proj: str) -> str:
    """真实用量落点：从项目目录逐级上溯找 `.qianbi_novel/usage/usage.jsonl`
    （实验 fake home 把用量隔离在假 home 那一层：cost_bench 跑中改 HOME，
    app.usage.FILE 是导入期算的，追不上假 home）。上溯有两条边界——到用户主目录
    为止、最多 MAX_HOME_UPWARD 层为止：一路走到文件系统根会把**别的书/用户真实
    控制台**的用量混进保险丝④的读数。找不到才回退 app.usage.FILE（全局用量）。"""
    from .. import usage as usage_mod
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    cur = os.path.abspath(proj or "")
    for _ in range(MAX_HOME_UPWARD):
        if not cur or os.path.normcase(cur) == home:
            break
        cand = os.path.join(cur, ".qianbi_novel", "usage", "usage.jsonl")
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return usage_mod.FILE


def usage_rows(proj: str) -> list:
    """usage.jsonl → 记录列表（缺文件/坏行容忍：跳过，与 app.usage._load 同口径）"""
    path = usage_path(proj)
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    rows.append(d)
    except OSError:
        return []
    return rows


def real_input_tokens(proj: str, last: bool = True) -> int:
    """卷会话输入规模的**实测值**（保险丝④的正解：用真 usage，不用字符启发式）。

    last=True（缺省）：取最近一笔会话相位的 prompt_tokens——"我现在带着多大的上下文
    发车"，压缩后下一笔立刻回落，触发器②因此不会在重置后逐章重复点火；
    last=False：最大单笔输入（审计读数，展示"压缩前长到过什么规模"）。
    无实测记录返回 0，调用方改走字符口径。"""
    rows = usage_rows(proj)
    best = 0
    for r in (reversed(rows) if last else rows):
        if (r.get("phase") or "") not in _SESSION_PHASES:
            continue
        try:
            v = int(r.get("in", 0) or 0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        if last:
            return v
        best = max(best, v)
    return best


def _session_stack_text(proj: str, volume: int = 0, gen: int = -1) -> str:
    """盘上卷会话栈全文（实测缺位时的字符口径原料）：`会话/卷N[_cK]_messages.jsonl`。
    volume=0 → 卷号最大者；gen=-1 → 该卷代次最大者（压缩后的新栈才是"当前会话"）。"""
    sess_dir = os.path.join(proj, "会话")
    if not os.path.isdir(sess_dir):
        return ""
    candidates = []
    for name in os.listdir(sess_dir):
        m = _STACK_FILE_RE.match(name)
        if not m:
            continue
        candidates.append((int(m.group(1)), int(m.group(2) or 0), os.path.join(sess_dir, name)))
    if not candidates:
        return ""
    scoped = [c for c in candidates if not volume or c[0] == int(volume)] or candidates
    if gen >= 0:
        scoped = [c for c in scoped if c[1] == gen] or scoped
    picked = max(scoped, key=lambda c: (c[0], c[1]))
    parts = []
    for line in project.read_file(picked[2]).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            parts.append(m["content"])
    return "\n\n".join(parts)


def session_input_estimate(proj: str, volume: int = 0) -> tuple:
    """「当前会话输入有多长」的读数（触发器② + 保险丝①基准）。
    Returns: (tokens, 口径标签)——实测优先（usage-measured，最近一笔），
    无实测退字符口径（han-caliber，本代栈全文）。绝不使用 DSH 的 4 字符/token。"""
    real = real_input_tokens(proj)
    if real > 0:
        return real, "usage-measured"
    return han_tokens(_session_stack_text(proj, volume)), "han-caliber"


# ==================== 触发器（§6.2）====================

def compaction_enabled(cfg: dict = None) -> bool:
    """旗标读数：writing.compaction（0.24.0 Q1-a 起默认开——质量标定，
    旧「默认关」让质量劣化全程发生在 800k 阈值之下，见模块头注释）。"""
    return bool(((cfg or {}).get("writing") or {}).get(FLAG_KEY, True))


def token_threshold(cfg: dict = None) -> int:
    try:
        return int(((cfg or {}).get("writing") or {}).get(THRESHOLD_KEY,
                                                          DEFAULT_TOKEN_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_THRESHOLD


def should_compact(proj: str, num: int, *, cfg: dict = None, manual: bool = False,
                   input_tokens: int = -1, volume: int = 0) -> Trigger:
    """§6.2 三个触发器（流水线在章循环里自动检查，零人工）：
    ① 卷界：本章是新一卷的第一章（大纲卷号变化）；
    ② 会话输入估算 ≥ 阈值（默认 800k tok；读数按保险丝④实测优先）；
    ③ 手动（UI 按钮传 manual=True）。
    flag 关闭时恒不触发——「模块不可达」的字节纪律。
    input_tokens 显式传入可旁路计量（调用方已有更准的读数时）。"""
    if not compaction_enabled(cfg):
        return Trigger("", "writing.compaction 关闭：不介入")
    prev = resolve_volume(proj, num - 1) if num > 1 else 0
    cur = resolve_volume(proj, num)
    if num > 1 and prev and cur and cur != prev:
        return Trigger("volume_boundary", f"卷界：第 {num} 章起进入卷 {cur}（上一章属卷 {prev}）")
    if manual:
        return Trigger("manual", f"手动请求压缩（截至第 {num} 章）")
    est = input_tokens if input_tokens >= 0 else session_input_estimate(proj, volume)[0]
    limit = token_threshold(cfg)
    if est >= limit:
        return Trigger("input_threshold", f"会话输入 {est} tok ≥ 阈值 {limit} tok")
    return Trigger("", f"未达阈值（实测/估算输入 {est} tok < {limit} tok）")


def resolve_volume(proj: str, num: int) -> int:
    """章号 → 卷号（复用 volume_session 的卷级大纲解析；解析不出回退卷 1）"""
    from .volume_session import resolve_volume_number
    return resolve_volume_number(proj, num)


# ==================== 原料装配 ====================

@dataclass(frozen=True)
class NearEnding:
    num: int
    title: str
    tail: str


def _heading_of(text: str) -> str:
    """正文文件首行标题（「# 第6章 0712」→「0712」），无标题给空串"""
    first = (text or "").lstrip().splitlines()[0] if (text or "").strip() else ""
    return re.sub(r"^#{0,6}\s*第\s*\d+\s*章\s*", "", first).strip()


def near_endings(proj: str, upto: int) -> tuple:
    """保险丝②：近 2 章结尾原文——第 N 章末 800 字 + 第 N-1 章末 400 字，逐字。
    锚点用 project.nearest_chapter_before（「取小于 num 的最近存在章」），
    补章/重写中间章时同样正确。tail 只切行尾空白（块内按原样内嵌，装配后逐字校验）。"""
    out = []
    ref = upto + 1
    for chars in NEAR_TAIL_CHARS:
        prev = project.nearest_chapter_before(proj, ref)
        if not prev:
            break
        text = project.read_file(prev[2]) or ""
        if not text.strip():
            break
        tail = (text[-chars:] if len(text) > chars else text).rstrip()
        out.append(NearEnding(num=prev[0], title=_heading_of(text), tail=tail))
        ref = prev[0]
    return tuple(out)


def chapter_prose(proj: str, volume: int, upto: int) -> str:
    """本卷 1..upto 章的逐字正文（保险丝①的「被替换历史」基准）。
    卷号解析失效（单卷书/自由体大纲）时按 upto 以下全部章节计。"""
    items = [(n, p) for n, _name, p in project.list_chapters(proj) if n <= upto]
    in_vol = [(n, p) for n, p in items if resolve_volume(proj, n) == volume]
    picked = in_vol or items
    return "\n\n".join(project.read_file(p) or "" for _n, p in picked)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def dedup_resident(body: str, resident: str) -> tuple:
    """保险丝③：逐行剔除常驻注入（system/章头）已有的内容。
    resident = 常驻注入全文；比对前两侧都做空白归一，整行命中即视为重复
    （markdown 缩进/换行差异不算新内容）。重复注入会引发行为异常（#5766），
    宁可少说不可重说。
    Returns: (保留文本, 剔除行数)"""
    res_norm = _norm(resident)
    kept, dropped = [], 0
    for line in (body or "").splitlines():
        norm = _norm(line)
        if norm and norm in res_norm:
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


def ledger_snapshot(proj: str, resident: str) -> dict:
    """台账快照（角色状态/时间线/伏笔/全局摘要）——先过保险丝③（不复述常驻），
    再按保险丝⑤补「以台账为准」的文件指针。伏笔沿用 memory.unfished_foreshadows
    （与章头同一字节源），全局摘要沿用 memory.read_global_summary（同）。"""
    sections = []
    for label, name in _LEDGER_ITEMS:
        if name == "伏笔":
            raw = memory.unfished_foreshadows(proj)
        else:
            raw = project.read_file(project.get_tracking_path(proj, name))
        kept, dropped = dedup_resident(raw, resident)
        sections.append({"label": label, "file": "追踪/%s.md" % name,
                         "body": kept[:LEDGER_BUDGET_CHARS], "dropped_lines": dropped})
    gsum, gdropped = dedup_resident(memory.read_global_summary(proj), resident)
    return {"sections": sections, "global_summary": gsum,
            "global_dropped_lines": gdropped}


# ==================== 渲染（确定性文本）====================

def render_handoff(volume: int, upto: int, endings: tuple, summaries: str,
                   ledger: dict) -> str:
    """交接块全文。零时间戳、零随机——同一盘态两次装配逐字节一致（sha256 可锁）。"""
    head = "【卷 %d 终交接块（截至第 %d 章 · 装配式压缩·零 LLM 调用）】" % (volume, upto)
    note = ("（本块是新卷开幕轮的叙事记忆。精确锚点——数值/日期/名单/物证位置——"
            "一律以台账为准，本块不复述系统常驻注入与章头台账各节已有内容。）")
    parts = [head, note]

    tail_lines = ["## 一、近程结尾原文（逐字保留，直接衔接用）"]
    for e in endings:
        tail_lines.append("### 第 %d 章%s结尾" % (e.num, ("《%s》" % e.title) if e.title else ""))
        tail_lines.append(e.tail)
    parts.append("\n".join(tail_lines))

    if (summaries or "").strip():
        parts.append("## 二、近 %d 章摘要\n%s" % (SUMMARY_WINDOW, summaries.strip()))

    gs = (ledger.get("global_summary") or "").strip()
    if gs:
        parts.append("## 三、主线进度（全局摘要·仅补章头未注入部分）\n" + gs)
    else:
        parts.append("## 三、主线进度（全局摘要）\n- 追踪/全局摘要.md 已随章头常驻注入，本块不重复")

    led = ["## 四、台账快照（常驻未覆盖部分；数值以台账为准）"]
    for sec in ledger.get("sections") or []:
        body = (sec.get("body") or "").strip()
        led.append("### %s（%s）" % (sec["label"], sec["file"]))
        led.append(body if body else "- 已全部随章头常驻注入，本块不重复")
    led.append("### 连续性台账（追踪/连续性台账.json）")
    led.append("- 人物/物件/制度/时间的精确锚点以台账为准，本块只作叙事记忆，不复述数值")
    parts.append("\n".join(led))
    return "\n\n".join(parts)


# ==================== 保险丝校验 ====================

def _shrink_ok(block_tokens: int, replaced_tokens: int) -> bool:
    """保险丝①：块必须**显著**小于被替换的整卷逐字历史（≤ SHRINK_MAX_RATIO）。
    不过即 fail-open——宁可不压缩，也不裁内容凑比例（那才是真丢连续性）。"""
    return replaced_tokens > 0 and block_tokens <= replaced_tokens * SHRINK_MAX_RATIO


def _verbatim_ok(block: str, endings: tuple) -> str:
    """保险丝②：近程尾巴必须一字不差地在块内（严格子串，不做空白归一——
    「逐字保留」没有近似档）。返回丢失的章号描述，完好返回空串。"""
    for e in endings:
        if e.tail not in block:
            return "第 %d 章结尾原文未逐字保留" % e.num
    return ""


# ==================== 保险丝⑥：因果链保链断言（WA5/B1+B8）====================
#
# 依据：superiter2 T3（Finding Flawed Fictions, arXiv 2504.11900）——摘要使连续性
# 错误检出率 +50%，根因是摘要丢掉因果环节；T4 §3.3（语义债务保链：保链断言是
# 五保险丝之外的第六根）。全部纯启发式、零 LLM、零网络、fail-open：
#
#   B1 提取（压缩前，从被替换历史）：collect_causal_assertions 三源——
#     ① cause_effect：正文里含因果连接词的句子，按连接词切两侧各成一个
#        「锚词槽」（断言只要求两侧都保持可检索，不判因果方向——方向错判
#        比漏检更危险）；
#     ② promise_payoff：伏笔账本未回收条目（承诺-兑现对的前半，承诺必须
#        存活到兑现章还读得到）；
#     ③ hook_response：钩子账本事件钩的 event_kw（埋下的钩子必须可被应答）。
#   B8 断言（压缩后）：assert_causal_chain 逐条核对——「语义在场」= 每个锚词槽
#     至少一个别名在归一化文本中可检索（normalize 为 C42 口径）。核对对象是
#     「交接块 + 开幕章常驻注入」的并集：保险丝③刻意不复述常驻内容，常驻也是
#     新栈持久前缀的一部分，单看块会假报丢失。交接块的每一级原料（常驻/近程
#     尾巴/近章摘要/全局摘要/台账快照）过同一断言并记录逐级归属——装配式压缩
#     的在场是全体层级的并集，任一级命中即算扛住。
#   失败处置：先降级「保链压缩」（失败句原文保底附加成第五节，句中自带锚词
#     → 附加后断言必然转绿，由复验证明）；追加后仍违反保险丝①（不再显著小于
#     被替换历史）才整笔拒绝压缩——保留原稿，绝不静默丢链。

# 因果连接词（长词优先，避免「因」类短词吃掉「因为」的前缀误切）
CAUSAL_CONNECTIVES = (
    "正因为", "之所以", "以至于", "是因为", "导致", "致使", "使得", "从而",
    "因而", "于是", "因此", "所以", "故而", "为此", "由于", "因为", "以致",
    "既然", "逼得", "害得",
)
_SENT_SPLIT_RE = re.compile(r"([^。！？!?；;\n]+[。！？!?；;]?)")
_CHAPTER_HEAD_RE = re.compile(r"^#{0,6}\s*第\s*(\d+)\s*章")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_QUOTED_TERM_RE = re.compile(r"[「『]([^「」『』]{2,16})[」』]")
# 锚词提纯：剪掉句法功能字（首尾修剪），整词命中停用词表则弃——
# 别名组是「任一命中即槽位在场」的可检索面，不求分词精确，宁松勿假报。
_TERM_STOP_CHARS = frozenset(
    "的了着呢吗吧呀啊嘛么之乎其把被给和与或也都就还很才便是在有进出去来上"
    "下中里外前后左右之间这那你我他她们它们哪谁啥")
_TERM_STOPWORDS = frozenset((
    "自己", "什么", "这个", "那个", "这么", "那么", "还是", "就是", "但是",
    "可是", "然而", "不过", "如果", "虽然", "而且", "并且", "或者", "只有",
    "已经", "正在", "将要", "时候", "之后", "以后", "然后", "起来", "出来",
    "过来", "下去", "上去", "一声", "不住", "不得", "那些", "这些", "这里",
    "那里", "地方", "事情", "东西", "一声",
))
MIN_SIDE_CHARS = 2              # 连接词两侧的最短有效长度
MAX_CAUSAL_ASSERTIONS = 32      # 断言清单总量上限（保底追加体积因此有界）
MAX_CE_ASSERTIONS = 16          # cause_effect 上限（每章前 MAX_CE_PER_CHAPTER 条）
MAX_CE_PER_CHAPTER = 2
MAX_PROMISE_ASSERTIONS = 8      # 未回收伏笔按账本紧迫序取前 8
MAX_HOOK_ASSERTIONS = 8         # 事件钩按章号取最近 8
CHAIN_SECTION_TITLE = "## 五、因果链保底（压缩断言清单未过——失败句原文保底附加）"
_HOOK_LEDGER_FILENAME = "钩子账本.json"


@dataclass(frozen=True)
class CausalAssertion:
    """一条「必须在压缩稿中保持语义在场」的因果链断言。

    slots：锚词槽的元组，每个槽是别名元组；在场判定 = 每个槽任一别名可检索
    （因果对两侧各一槽、承诺/钩子单槽）。sentence：原句/原名——保链降级时
    逐字附加进块的原材料。"""
    kind: str            # cause_effect | promise_payoff | hook_response
    chapter: int         # 来源章（账本源无章号给 0）
    slots: tuple         # tuple[tuple[str, ...], ...]
    sentence: str
    source: str = ""     # 命中的启发式描述（审计用）


@dataclass(frozen=True)
class CausalReport:
    """B8 断言报告。levels：{断言序号字符串化: 首个满足它的层级名}（失败为 ""）
    ——逐级接入的机读诊断：哪一级扛住了哪条因果链。"""
    checked: int
    failed: tuple
    levels: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.checked == 0 or not self.failed


def causal_terms(side: str) -> tuple:
    """连接词单侧文本 → 锚词别名组（纯启发式）：引用词「」『』优先，
    其余取 CJK/字母数字连串剪掉首尾功能字后的片段（≤4 字整串，>4 字取
    首二/次二/末二三个片段）。顺序确定（dict.fromkeys 去重保序），上限 4 个。"""
    aliases = list(_QUOTED_TERM_RE.findall(side or ""))
    for run in _CJK_RUN_RE.findall(side or ""):
        s, e = 0, len(run)
        while s < e and run[s] in _TERM_STOP_CHARS:
            s += 1
        while e > s and run[e - 1] in _TERM_STOP_CHARS:
            e -= 1
        run = run[s:e]
        if len(run) < 2 or run in _TERM_STOPWORDS:
            continue
        if len(run) <= 4:
            aliases.append(run)
        else:
            aliases.extend((run[:2], run[2:4], run[-2:]))
    out = []
    for a in dict.fromkeys(aliases):
        if len(a) >= 2 and a not in _TERM_STOPWORDS:
            out.append(a)
        if len(out) >= 4:
            break
    return tuple(out)


def _split_causal_sentence(sent: str):
    """含因果连接词的句子 → (左半, 连接词, 右半)；首个命中连接词的两侧任一
    过短即整句放弃（不换词再切，防碎句假断言）。"""
    for conn in CAUSAL_CONNECTIVES:
        i = sent.find(conn)
        if i <= 0:
            continue
        left, right = sent[:i], sent[i + len(conn):]
        if len(left.strip()) >= MIN_SIDE_CHARS and len(right.strip()) >= MIN_SIDE_CHARS:
            return left, conn, right
        return None
    return None


def extract_prose_assertions(history_text: str) -> tuple:
    """B1 源①：被替换历史正文里的「A 导致 B」句对（每章取最先出现的
    MAX_CE_PER_CHAPTER 条——因果句在章内越靠前越贴节拍位）。"""
    out, cur_ch, taken, seen = [], 0, 0, set()
    for line in (history_text or "").splitlines():
        m = _CHAPTER_HEAD_RE.match(line.strip())
        if m:
            cur_ch, taken = int(m.group(1)), 0
            continue
        for sent in _SENT_SPLIT_RE.findall(line):
            sent = sent.strip()
            if not (8 <= len(sent) <= 160) or sent in seen:
                continue
            parts = _split_causal_sentence(sent)
            if parts is None:
                continue
            left, conn, right = parts
            l_terms, r_terms = causal_terms(left), causal_terms(right)
            if not l_terms or not r_terms:
                continue
            seen.add(sent)
            out.append(CausalAssertion(
                kind="cause_effect", chapter=cur_ch, slots=(l_terms, r_terms),
                sentence=sent, source="因果连接词「%s」" % conn))
            taken += 1
            if taken >= MAX_CE_PER_CHAPTER:
                break
    return tuple(out[:MAX_CE_ASSERTIONS])


def extract_foreshadow_assertions(proj: str) -> tuple:
    """B1 源②：未回收伏笔（memory.unfished_foreshadows 的紧迫序渲染表——
    与交接块台账快照/章头常驻同一字节源）。承诺名词（含 ·/: 分隔的子词）
    即锚词槽；解析不出表行就零断言（fail-open）。"""
    try:
        table = memory.unfished_foreshadows(proj)
    except Exception:  # noqa: BLE001
        return ()
    out = []
    for line in (table or "").splitlines():
        t = line.strip()
        if not (t.startswith("|") and t.endswith("|")):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("伏笔", "名称", ""):
            continue
        core = t.replace("|", "").replace(" ", "").strip("-:")
        if not core:
            continue            # 表头分隔行
        name = re.sub(r"^【[^】]*】", "", cells[0]).strip()   # 剥【超期N章】前缀
        if len(name) < 2:
            continue
        parts = [p.strip() for p in re.split(r"[·•:：/／]+", name) if len(p.strip()) >= 2]
        aliases = tuple(dict.fromkeys([name] + parts))[:4]
        out.append(CausalAssertion(kind="promise_payoff", chapter=0,
                                   slots=(aliases,), sentence=name,
                                   source="伏笔账本未回收条目"))
        if len(out) >= MAX_PROMISE_ASSERTIONS:
            break
    return tuple(out)


def _read_hook_rows(proj: str) -> list:
    """追踪/钩子账本.json 容错读（JSON 数组 / {"rows":[...]} / jsonl 行三种形态）。
    缺失/损坏 → []（fail-open；卡4 的落账接线不在本模块，读侧只认公共键）。"""
    path = os.path.join(proj, "追踪", _HOOK_LEDGER_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        data = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                data.append(json.loads(ln))
            except ValueError:
                return []
    if isinstance(data, dict):
        data = data.get("rows")
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def extract_hook_assertions(proj: str) -> tuple:
    """B1 源③：事件钩的 event_kw（钩子应答标记——埋钩关键词必须存活到应答章）。
    按章号取最近 MAX_HOOK_ASSERTIONS 条。"""
    rows = [r for r in _read_hook_rows(proj) if str(r.get("event_kw") or "").strip()]
    rows.sort(key=lambda r: (int(r.get("num") or 0), str(r.get("position") or "")))
    out = []
    for r in rows[-MAX_HOOK_ASSERTIONS:]:
        kw = str(r.get("event_kw")).strip()
        aliases = tuple(dict.fromkeys(
            [kw] + _QUOTED_TERM_RE.findall(kw)))[:4]
        out.append(CausalAssertion(
            kind="hook_response", chapter=int(r.get("num") or 0),
            slots=(aliases,), sentence=kw, source="钩子账本事件钩 event_kw"))
    return tuple(out)


def collect_causal_assertions(proj: str, history_text: str) -> tuple:
    """B1 总入口：三源合并成压缩前断言清单（顺序稳定：因果句→伏笔承诺→钩子）。"""
    assertions = (extract_prose_assertions(history_text)
                  + extract_foreshadow_assertions(proj)
                  + extract_hook_assertions(proj))
    return tuple(assertions[:MAX_CAUSAL_ASSERTIONS])


def _slot_hit(aliases: tuple, norm_text: str) -> bool:
    return any(normalize(a) in norm_text for a in aliases if a)


def assertion_satisfied(a: CausalAssertion, norm_text: str) -> bool:
    """单个断言的在场判定：每个锚词槽至少一个别名可检索（norm_text 须已过
    normalize——与 fact_ledger 锚定同口径，引号/全半角/空白差不假报）。"""
    return bool(a.slots) and all(_slot_hit(s, norm_text) for s in a.slots)


def assert_causal_chain(levels, assertions) -> CausalReport:
    """B8 总入口：每一级原料过同一断言（levels = (层级名, 文本) 有序对）。

    在场 = 全体层级归一化并集中可检索（装配式压缩的语义并集口径）；levels
    记录每条断言的逐级归属（首个满足它的层级；全不满足 → 失败 + 归属空串）。"""
    assertions = tuple(assertions or ())
    norm_levels = [(name, normalize(text or "")) for name, text in (levels or [])]
    arena = "".join(n for _name, n in norm_levels)
    failed, levels_map = [], {}
    for i, a in enumerate(assertions):
        hit_level = ""
        if assertion_satisfied(a, arena):
            for name, n in norm_levels:
                if assertion_satisfied(a, n):
                    hit_level = name
                    break
        else:
            failed.append(a)
        levels_map[str(i)] = hit_level
    return CausalReport(checked=len(assertions), failed=tuple(failed),
                        levels=levels_map)


def render_chain_appendix(failed) -> str:
    """保链降级的保底附加节（第五节）：失败断言的原句逐字入块。句中自带它的
    锚词别名 → 附加后断言必然转绿（由 build 内的复验证明）。零时间戳，确定性。"""
    lines = [CHAIN_SECTION_TITLE,
             "（以下原句因压缩稿未保住其因果语义而整句保底；精确锚点仍以台账为准）"]
    for a in failed:
        label = "第%d章" % a.chapter if a.chapter else "前文"
        lines.append("- [%s·%s] %s" % (a.kind, label, a.sentence))
    return "\n".join(lines)


def assertion_payload(assertions: tuple) -> list:
    """断言清单 → 机读形态（交接块 json 的 sections.causal.assertions，
    读侧复验与审计共用同一形状）。"""
    return [{"kind": a.kind, "chapter": a.chapter, "sentence": a.sentence,
             "slots": [list(s) for s in a.slots]} for a in assertions]


def assertions_from_payload(items) -> tuple:
    """机读形态 → 断言对象（读侧复验用）；坏条目跳过（fail-open）。"""
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not isinstance(it.get("slots"), list):
            continue
        slots = tuple(tuple(str(x) for x in s if str(x))
                      for s in it["slots"] if isinstance(s, list))
        try:
            ch = int(it.get("chapter") or 0)
        except (TypeError, ValueError):
            ch = 0
        out.append(CausalAssertion(kind=str(it.get("kind") or ""), chapter=ch,
                                   slots=slots, sentence=str(it.get("sentence") or "")))
    return tuple(out)


def _record_causal_event(proj: str, volume: int, upto: int, report: CausalReport,
                         *, degraded: bool, rejected: bool) -> None:
    """保险丝⑥告警（W-3 同纪律：纯观测件，任何失败静默）——断言失败必留现场：
    compaction_causal{checked, failed, degraded, rejected, kinds}。"""
    try:
        from .volume_session import record_event
        record_event(proj, "compaction_causal", volume=int(volume), upto=int(upto),
                     checked=int(report.checked), failed=len(report.failed),
                     degraded=1 if degraded else 0, rejected=1 if rejected else 0,
                     kinds=",".join(sorted({a.kind for a in report.failed})))
    except Exception:  # noqa: BLE001
        pass


def _record_stale_event(proj: str, volume: int, num: int, failed: int) -> None:
    """读侧复验失败的现场（handoff_causal_stale）：不复用旧块、转现场重装配。"""
    try:
        from .volume_session import record_event
        record_event(proj, "handoff_causal_stale", volume=int(volume), num=int(num),
                     failed=int(failed))
    except Exception:  # noqa: BLE001
        pass


# ==================== 产物落盘（§6.2）====================

def handoff_md_path(proj: str, volume: int) -> str:
    """交接块 Markdown 落点：追踪/交接块_卷N.md（用 project.get_tracking_path）"""
    return project.get_tracking_path(proj, "交接块_卷%d" % int(volume))


def handoff_json_path(proj: str, volume: int) -> str:
    """交接块 JSON 落点：追踪/交接块_卷N.json（与 连续性台账.json 同层同风格）"""
    return os.path.join(proj, "追踪", "交接块_卷%d.json" % int(volume))


def save_handoff(proj: str, volume: int, payload: dict) -> tuple:
    """双写 md + json（md 走 project.write_file，json 与台账同一落盘风格）。
    块文本本身不含行尾换行（sha256 三处一致：结果对象 / json / 开幕块），
    md 文件按仓库惯例补一个行尾换行。"""
    md_path = handoff_md_path(proj, volume)
    project.write_file(md_path, (payload.get("text") or "") + "\n")
    js_path = handoff_json_path(proj, volume)
    os.makedirs(os.path.dirname(js_path), exist_ok=True)
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return (md_path, js_path)


def load_handoff(proj: str, volume: int) -> dict:
    """读回交接块 json（断点续跑：volume_session 的 load 链路据此重建开幕块）；
    缺失/损坏/非交接块 kind → 空 dict（调用方按「无交接块」继续，绝不抛）。"""
    path = handoff_json_path(proj, volume)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict) or d.get("kind") != ARTIFACT_KIND:
        return {}
    return d


# ==================== 主入口 ====================

def build_handoff_block(proj: str, *, cfg: dict = None, upto: int = 0,
                        volume: int = 0, trigger: str = "manual",
                        resident_texts: tuple = None, write: bool = True,
                        replaced_hint: int = 0) -> HandoffResult:
    """装配式卷终交接块（§4.3 项 2 + §6.3，零 LLM 调用）。

    upto：本卷最后一章（缺省 = 盘上已定稿的最大章号）；volume：缺省按 upto 解析。
    resident_texts：常驻注入全文（保险丝③的去重基准）；缺省 = project_header +
                     下一章章头（volume_mode，即新卷开幕轮实际携带的那一份）。
    replaced_hint：被顶替历史的真实规模（tok）——调用方按会话栈实测传入
                     （T 轮报告 §9-B：单章正文口径严重失真，真实 285,683→17,644
                     是 93.8% 而日志曾报 80%）；缺省 0 退回单章口径（仅兜底）。
    write=False：只装配不落盘（调用方先验货再决定写）。
    任何一条保险丝不过 → HandoffResult(ok=False, text="", reason=...)，不落盘。
    保险丝⑥（因果断言，WA5）失败先降级「保链压缩」（失败句原文保底附加，
    degraded=True + session_events 告警），追加后仍违反保险丝①才整笔拒绝。
    """
    if not compaction_enabled(cfg):
        return HandoffResult(ok=False, flag_on=False, trigger=trigger,
                             reason="writing.compaction 关闭：本模块不介入（字节不变纪律）")
    nums = sorted(n for n, _name, _p in project.list_chapters(proj) if n <= (upto or 10 ** 9))
    upto = int(upto or (nums[-1] if nums else 0))
    if upto <= 0:
        return HandoffResult(ok=False, trigger=trigger,
                             reason="拒绝：盘上没有任何已定稿章节")
    vol = int(volume or resolve_volume(proj, upto) or 1)
    endings = near_endings(proj, upto)
    if not endings:
        return HandoffResult(ok=False, trigger=trigger, volume=vol, to_chapter=upto,
                             reason="拒绝：近程结尾原文缺失（无已定稿正文可保留）")
    summaries = memory.read_recent_summaries(proj, upto + 1, n=SUMMARY_WINDOW)
    if resident_texts is None:
        from .shared_prefix import chapter_header, project_header
        resident_texts = (project_header(proj),
                          chapter_header(proj, upto + 1, volume_mode=True))
    ledger = ledger_snapshot(proj, "\n\n".join(t or "" for t in resident_texts))
    text = render_handoff(vol, upto, endings, summaries, ledger)
    tokens, meter = han_tokens(text), "han-caliber"
    # V1-b（T 轮报告 §9-B）：被顶替量优先取调用方按会话栈实测的 replaced_hint；
    # 单章正文口径只是无 hint 时的兜底（严重低估，曾把 93.8% 的真实压缩报成 80%）。
    # 被替换历史全文同时是保险丝⑥因果断言的提取原料（B1），无条件读一次。
    replaced_text = chapter_prose(proj, vol, upto)
    replaced = int(replaced_hint or 0) or han_tokens(replaced_text)
    if not _shrink_ok(tokens, replaced):
        return HandoffResult(ok=False, tokens=tokens, replaced_tokens=replaced,
                             shrunk=False, meter=meter, trigger=trigger, volume=vol,
                             from_chapter=endings[-1].num, to_chapter=upto,
                             reason="保险丝①拒绝：交接块 %d tok 未显著小于被替换历史 %d tok"
                                    "（比例 %.3f > %.2f）——fail-open 不压缩"
                                    % (tokens, replaced,
                                       (tokens / replaced if replaced else 1.0),
                                       SHRINK_MAX_RATIO))
    lost = _verbatim_ok(text, endings)
    if lost:
        return HandoffResult(ok=False, tokens=tokens, replaced_tokens=replaced,
                             shrunk=True, meter=meter, trigger=trigger, volume=vol,
                             to_chapter=upto, reason="保险丝②拒绝：%s" % lost)
    # ---- 保险丝⑥（WA5/B1+B8）：压缩前提取因果断言清单，压缩稿逐条核对 ----
    # 逐级接入：交接块的每一级原料 + 开幕章常驻注入过同一 assert_causal_chain
    # （保险丝③刻意不复述常驻内容，常驻也是新栈持久前缀——在场按并集判定）。
    levels = (
        ("resident", "\n".join(t or "" for t in resident_texts)),
        ("near_endings", "\n".join(e.tail for e in endings)),
        ("recent_summaries", summaries or ""),
        ("global_summary", ledger.get("global_summary") or ""),
        ("ledger", "\n".join((s.get("body") or "")
                             for s in ledger.get("sections") or [])),
    )
    assertions = collect_causal_assertions(proj, replaced_text)
    report = assert_causal_chain(levels, assertions)
    failed_initial = len(report.failed)
    degraded = False
    if not report.ok:
        # 降级「保链压缩」：失败句原文保底附加（句中自带锚词 → 附加后必转绿）；
        # 追加后仍不显著小于被替换历史 → 整笔拒绝（保留原稿，fail-open 不压缩）。
        appendix = render_chain_appendix(report.failed)
        degraded_text = text + "\n\n" + appendix
        d_tokens = han_tokens(degraded_text)
        if _shrink_ok(d_tokens, replaced) and not _verbatim_ok(degraded_text, endings):
            text, tokens, degraded = degraded_text, d_tokens, True
            _record_causal_event(proj, vol, upto, report, degraded=True, rejected=False)
            report = assert_causal_chain(
                levels + (("chain_appendix", appendix),), assertions)
        else:
            _record_causal_event(proj, vol, upto, report, degraded=False, rejected=True)
            return HandoffResult(
                ok=False, tokens=tokens, replaced_tokens=replaced, shrunk=True,
                meter=meter, trigger=trigger, volume=vol,
                from_chapter=endings[-1].num, to_chapter=upto,
                causal_checked=report.checked, causal_failed=len(report.failed),
                reason="保险丝⑥拒绝：%d 条因果断言未保，且保底追加后交接块 %d tok "
                       "不再显著小于被替换历史 %d tok（> %.2f）——fail-open 保留原稿"
                       % (len(report.failed), d_tokens, replaced, SHRINK_MAX_RATIO))
    payload = {"kind": ARTIFACT_KIND, "version": ARTIFACT_VERSION, "volume": vol,
               "from_chapter": endings[-1].num, "to_chapter": upto,
               "trigger": trigger, "text": text, "tokens": tokens,
               "replaced_tokens": replaced, "shrink_ratio": round(tokens / replaced, 4),
               "token_meter": meter,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "sections": {"near_endings": [{"num": e.num, "title": e.title,
                                              "tail": e.tail} for e in endings],
                            "recent_summaries": summaries,
                            "ledger": ledger,
                            "causal": {"checked": report.checked,
                                       "failed_initial": failed_initial,
                                       "failed": len(report.failed),
                                       "degraded": degraded,
                                       "assertions": assertion_payload(assertions)}}}
    artifacts = save_handoff(proj, vol, payload) if write else ()
    return HandoffResult(ok=True, text=text, tokens=tokens, replaced_tokens=replaced,
                         shrunk=True, meter=meter, trigger=trigger, volume=vol,
                         from_chapter=endings[-1].num, to_chapter=upto,
                         artifacts=artifacts, sections=payload["sections"],
                         causal_checked=report.checked, causal_failed=failed_initial,
                         degraded=degraded)


# ==================== 接回（新会话开幕块）====================

def opening_block(proj: str, num: int, *, cfg: dict = None, volume: int = 0,
                  replaced_hint: int = 0) -> OpeningBlock:
    """新卷开幕块的入口（供 stages 接线）：返回交接块全文 + 稳定 sha256。

    读侧确定性：零 LLM、零网络。查找顺序（V1-a，T 轮报告 §9-A）：先本卷
    （卷内压缩块更新鲜）、再上一卷（卷界交接）；**块只在其 to_chapter ≥ num-1
    （完整覆盖到本章前一章）时直接复用**——陈旧块落到下方现场重装配，按 upto
    的真实卷落盘。T2 实测缺陷：ch25 复用 ch21 的陈旧块（卷号错位+读侧先查旧卷）
    丢了 21-24 章记忆，幂等守卫全程失效。
    volume = **本章**所属卷号（缺省按大纲解析），不是交接块自身的卷号。
    replaced_hint：现场装配时传给 build_handoff_block 的被顶替实测规模（tok）。
    **flag 关闭时恒返回空文本**——本模块对请求体的字节贡献为 0。
    """
    if not compaction_enabled(cfg):
        return OpeningBlock(reason="writing.compaction 关闭：开幕块不介入")
    cur = int(volume or resolve_volume(proj, num) or 1)
    from .shared_prefix import chapter_header, project_header
    resident_norm = ""
    for v in (cur, cur - 1):
        if v < 1:
            continue
        d = load_handoff(proj, v)
        text = (d.get("text") or "")
        if text.strip() and int(d.get("to_chapter") or 0) >= num - 1:
            # 保险丝⑥读侧复验（WA5/B8）：盘上块若带着断言清单，先按「块+本章
            # 常驻注入」复核在场——建档后被改动的台账可能已把某条因果链的唯一
            # 载体抽走；复验失败就不复用旧块，落到下方现场重装配（带完整保链
            # 管线）。无 causal 节的历史产物照旧复用（兼容，skip）。
            stored = ((d.get("sections") or {}).get("causal") or {}).get("assertions")
            if stored:
                if not resident_norm:
                    resident_norm = normalize(
                        project_header(proj) + "\n"
                        + chapter_header(proj, num, volume_mode=True))
                stale = [a for a in assertions_from_payload(stored)
                         if not assertion_satisfied(a, resident_norm)]
                if stale:
                    _record_stale_event(proj, v, num, len(stale))
                    break
            return OpeningBlock(text=text, tokens=int(d.get("tokens") or han_tokens(text)),
                                contributed=True, reason="handoff_卷%d" % v,
                                replaced_tokens=int(d.get("replaced_tokens") or 0),
                                shrink_ratio=float(d.get("shrink_ratio") or 1.0))
    if cur > 1 or num > 1:
        res = build_handoff_block(proj, cfg=cfg, upto=num - 1, volume=0,
                                  replaced_hint=replaced_hint)
        if res.ok and res.text.strip():
            return OpeningBlock(text=res.text, tokens=res.tokens, contributed=True,
                                reason="assembled:" + (res.trigger or "manual"),
                                replaced_tokens=res.replaced_tokens,
                                shrink_ratio=res.shrink_ratio)
        return OpeningBlock(reason=res.reason or "无可用交接块")
    return OpeningBlock(reason="首卷首章：没有需要交接的历史")


def compose_open_turn(proj: str, num: int, chapter_header_text: str,
                      first_turn_text: str, *, cfg: dict = None,
                      volume: int = 0) -> str:
    """卷会话开幕轮（与 VolumeSession.open_chapter 同一字节序）：
    开幕声明 → [交接块] → 章头 → 本章首个相位轮。

    flag 关闭 / 无交接块时中间那节不存在，输出与 volume_session 现状**逐字节一致**
    （交接块插在章头之前 = 卷终状态块在前、本章上下文在后，静态前置动态殿后）。
    """
    from .volume_session import opening_marker
    ob = opening_block(proj, num, cfg=cfg, volume=volume)
    parts = [opening_marker(num) if num else _MID_VOLUME_MARK]
    if ob.contributed and ob.text.strip():
        parts.append(ob.text)
    if (chapter_header_text or "").strip():
        parts.append(chapter_header_text)
    parts.append(first_turn_text)
    return "\n\n".join(p for p in parts if p)
