# -*- coding: utf-8 -*-
"""D-stages（0.23.0）stages 接线批：章纲合同/覆盖拒收/伏笔回补/白名单/快照

- A1：_mc_assemble 挂 parse_directive+validate_directive——缺必填字段出 fail 候选
  warn（G4 风格，不阻断）；合同块经 to_prompt_block 注入正文轮（S4/会话/单轮
  三分支同注入位）；零识别字段细纲装配字节不变。
- A2：must_cover_nodes 对照正文（确定性零 LLM），缺失≥1 合成「[大纲覆盖]」阻塞票
  走既有 REJECT 修复环（带缺失清单，受 review_max_rounds 上限约束）。
- B4：章重写（_mc_finalize 归档分支）接 tracking_store.rollback_foreshadow_advances。
- 白名单：stages 四个 scan_deslop 调用点传 proj（书级 .deslop-whitelist 生效）。
- E1：ctx.prompt_snapshots[kind] 内存快照（章入口清零）；debug.prompt_snapshot_dir
  落盘（默认 off）。

LLM 用相位队列假件（test_microcycle_steps 同思路）；除假 client 外全真身。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project as pj
from app.core import gates, stages, tracking_store as ts
from app.core import state as st

_BASE = "草稿内容这是一段完整的测试正文。"
_COVER_NODE = "黑袍人现身 | 祠堂 | 令牌"


def _contract_outline():
    """合同化细纲：必填九字段齐全 + must_cover_nodes 一项（A2 对照源）"""
    return ("### 第1章 开端\n"
            "- 目标：少年夺回玉简\n"
            "- 时间锚点：主线第 1 日\n"
            "- 承接节点：少年离乡\n"
            "- 推进节点：夜探祠堂、初遇老者\n"
            "- 章末节点：令牌到手\n"
            f"- 必须覆盖节点：{_COVER_NODE}\n"
            "- 章末未闭合问题：黑袍人是谁\n"
            "- 钩型：悬念\n"
            "- 期待度：强\n")


def _legacy_outline():
    """自由版式细纲（只命中 goal 一个字段，余皆缺）——legacy 装配纪律样本"""
    return "### 开端\n- 核心事件：少年拾到玉简"


def _draft(extra=""):
    return "## 第1章 开端\n\n" + _BASE * 40 + extra


_PASS_REVIEW = (
    "===A_GOLDEN_OPEN=== pass 开篇有钩子 【原文引证：“%s”】\n"
    "===B_PAYOFF=== pass 爽点当章结算 【原文引证：“%s”】\n"
    "===C_FINGER=== pass 金手指合规\n"
    "===D_PLOT=== pass 因果自洽\n"
    "===E_CHARACTER=== pass 声口一致\n"
    "===F_HOOK=== pass 章尾有钩\n"
    "===TOTAL=== pass=6 marginal=0 fail=0\n"
    "===VERDICT===\nPASS\n===ITEMS===\n===END===\n"
) % (_BASE, _BASE)


class _CapturingClient:
    """相位队列假件 + prompt 捕获：断言 findings/合同块真的进了装配 prompt"""

    def __init__(self, responses=None):
        self.responses = {k: list(v) for k, v in (responses or {}).items()}
        self.prompts = {}               # phase → [prompt]
        self.calls = []

    def _next(self, phase, prompt):
        self.calls.append(phase)
        self.prompts.setdefault(phase, []).append(prompt)
        q = self.responses.get(phase)
        if not q:
            return ""
        return q.pop(0) if len(q) > 1 else q[0]

    def chat_stream(self, prompt, on_chunk=None, phase="", **kw):
        return self._next(phase, prompt)

    def chat(self, prompt, **kw):
        return self._next("chat", prompt)


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _WiringCtx:
    """微循环假 ctx（test_microcycle_steps._PinCtx 同款接口面）"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.logs = []
        self.last_prompt = ""
        self.review_raw = ""
        self.gen_trace = []
        self.gen_worldbooks = {}
        self.timeline = []
        self.prompt_snapshots = {}      # E1：章入口会被 chapter_microcycle 清零重建

    def gate(self, key, summary="", chapter=0):
        return ""

    def consume_gate_idea(self):
        return ""

    def checkpoint(self):
        pass

    def step(self, num, key):
        self.timeline.append((num, key))

    def log(self, level, msg):
        self.logs.append(f"{level}|{msg}")

    def stream_chunk(self, text):
        pass

    def stream_stage(self, label):
        pass

    def auto_pause(self, reason):
        self.logs.append(f"auto_pause|{reason}")


def _mk_proj(tmp_path, outline_fn=_legacy_outline):
    proj = str(tmp_path / "接线书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(pj.get_outline_path(proj, 1), outline_fn())
    return proj


def _cfg(target=600, **gates_extra):
    gates_c = {"review_enabled": False, "deslop_max_rounds": 1, "word_enrich_rounds": 1}
    gates_c.update(gates_extra)
    return {"gates": gates_c,
            "writing": {"chapter_word_target": target},
            "llm": {"max_retries": 0}}


def _review_cfg(**kw):
    fake_conn = {"id": "rv", "name": "rv", "base_url": "https://example.test",
                 "api_key": "sk-test", "model": "test-model"}
    cfg = _cfg(review_enabled=True, review_votes=1, review_votes_recheck=1, **kw)
    cfg["connections"] = [fake_conn]
    cfg["slots"] = {"writing": "rv", "helper": "rv", "review": "rv"}
    return cfg


# ---------------- A1：合同校验 fail 候选（G4 warn 风格，不阻断） ----------------

def test_a1_missing_required_fields_log_as_fail_candidates(tmp_path):
    """legacy 细纲只命中 goal → 缺必填清单出 warn 候选，流程照常走完（不阻断）"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    warn = [lg for lg in ctx.logs if "细纲合同校验：缺必填字段" in lg]
    assert warn, "缺必填字段必须出 fail 候选 warn"
    assert "goal" not in warn[0] and "must_cover_nodes" in warn[0] \
        and "cbn" in warn[0], f"缺字段清单口径漂移：{warn[0]}"
    assert "不阻断" in warn[0]
    assert [k for _n, k in ctx.timeline] == ["assemble", "draft", "scan", "finalize"], \
        "warn 候选不许改变七步序列"
    assert record["num"] == 1


def test_a1_complete_contract_no_warning(tmp_path):
    """合同完备细纲不出缺字段 warn；解析容错不炸"""
    proj = _mk_proj(tmp_path, _contract_outline)
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)
    assert not [lg for lg in ctx.logs if "细纲合同校验" in lg], "完备合同不该出校验 warn"


# ---------------- A1：合同块注入（三分支同注入位 + legacy 零漂移纪律） ----------------

def test_a1_contract_block_injected_into_prose_prompt(tmp_path):
    """合同化细纲：正文轮 prompt 含 17 字段合同块（含 must_cover_nodes 原文）"""
    proj = _mk_proj(tmp_path, _contract_outline)
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)

    prose_prompt = ctx.prompt_snapshots.get("prose") or ""
    assert "本章细纲合同" in prose_prompt, "正文轮必须注入合同块"
    assert "必须覆盖节点" in prose_prompt and _COVER_NODE in prose_prompt
    assert any("本章细纲合同" in p for p in client.prompts.get("prose", [])), \
        "注入必须发生在发给模型的装配 prompt 里（不只存快照）"


def test_a1_legacy_outline_keeps_prose_prompt_block_free(tmp_path):
    """零识别字段之外只有 goal 的 legacy 细纲：合同块不注入（装配字节纪律）。

    注意：legacy 样本「核心事件」命中 goal——合同块注入只认「≥1 个识别字段」，
    goal 在场即注入；本钉保证的是**完全无字段命中**的细纲不出块（构造一个
    纯叙述细纲验证空串纪律），goal 在场的 legacy 注入属 A1 预期行为。
    """
    proj = _mk_proj(tmp_path)
    pj.write_file(pj.get_outline_path(proj, 1), "### 开端\n少年在祠堂外拾到一枚玉简。\n")
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)
    prose_prompt = ctx.prompt_snapshots.get("prose") or ""
    assert prose_prompt, "E1 快照必须存在"
    assert "本章细纲合同" not in prose_prompt, "零识别字段=空串，装配字节不变"


# ---------------- A2：大纲覆盖拒收（带缺失清单，走既有 REJECT 修复环） ----------------

def test_a2_missing_node_rejects_and_fix_round_adopts_repair(tmp_path):
    """审校 PASS 但缺覆盖节点 → 合成阻塞票进修复环；修复稿补齐节点后被采纳"""
    proj = _mk_proj(tmp_path, _contract_outline)
    fixed = _draft("黑袍人现身祠堂夺走令牌。")
    client = _CapturingClient({"prose": [_draft()],
                               "review": [_PASS_REVIEW, _PASS_REVIEW],
                               "review_fix": [fixed]})
    ctx = _WiringCtx(proj, _review_cfg(review_max_rounds=2), client)
    record = stages.chapter_microcycle(ctx, 1)

    rej = [lg for lg in ctx.logs if "大纲覆盖拒收" in lg]
    assert rej and "1 个必须覆盖节点未命中" in rej[0], "缺失≥1 必须合成拒收票"
    # 缺失清单进修复 prompt（findings 可消费）
    fix_prompts = client.prompts.get("review_fix", [])
    assert fix_prompts and "[大纲覆盖]" in fix_prompts[0] and _COVER_NODE in fix_prompts[0], \
        "合成票必须带缺失节点原文清单"
    # 修复稿补齐节点 → 复检同池计数改善 → 采纳
    assert record["status"] == "pass" and record["review_blocking"] == 0
    chapters = pj.list_chapters(proj)
    assert "黑袍人现身" in pj.read_file(chapters[0][2]), "补齐覆盖节点的修复稿应被采纳"
    assert any("审校通过（复检 1 轮" in lg for lg in ctx.logs)


def test_a2_unrepairable_node_exhausts_existing_round_cap(tmp_path):
    """修复稿不补节点 → 覆盖票不改善走既有「未改善保留原稿」+ 轮尽待修收口"""
    proj = _mk_proj(tmp_path, _contract_outline)
    client = _CapturingClient({"prose": [_draft()],
                               "review": [_PASS_REVIEW, _PASS_REVIEW],
                               "review_fix": [_draft("夜里起了风，祠堂门被吹开。")]})
    ctx = _WiringCtx(proj, _review_cfg(review_max_rounds=1), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert any("大纲覆盖拒收" in lg for lg in ctx.logs)
    assert any("审校修复未改善（1→1 处）" in lg for lg in ctx.logs), \
        "覆盖票与审校票同池计数：不改善按既有语义保留原稿"
    assert record["status"] == "needs_fix", "轮尽仍缺节点 = 拒收收口（needs_fix）"
    assert any("待修" in lg for lg in ctx.logs)


def test_a2_covered_node_no_rejection(tmp_path):
    """正文已含全部要件 → 不出覆盖拒收（确定性对照零误报样本）"""
    proj = _mk_proj(tmp_path, _contract_outline)
    client = _CapturingClient({"prose": [_draft("黑袍人现身祠堂夺走令牌。")]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)
    assert not [lg for lg in ctx.logs if "大纲覆盖拒收" in lg]


# ---------------- B4：章重写接 rollback_foreshadow_advances ----------------

def test_b4_rewrite_finalize_rolls_back_foreshadow_advances(tmp_path):
    """重写定稿（旧稿在场且有变）→ 本章旧稿推进撤销、日志清零可重登记"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    from app.core import versions
    # 旧稿已定稿过：v1=更早版本（与盘上旧稿不同，避开 snapshot 同内容去重），
    # 盘上旧稿=v_current（finalize 将归档的 old_text），且本章按旧稿登记过伏笔推进
    versions.snapshot(proj, 1, _draft(), versions.SOURCE_FINALIZE)
    old_text = _draft("旧稿在场的版本。")
    chapter_path = pj.get_chapter_path(proj, 1, "开端")
    pj.write_file(chapter_path, old_text)
    with open(os.path.join(proj, "追踪", "伏笔表.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rows": [{"伏笔": "黑袍人的令牌", "类别": "物",
                                           "埋设章节": "第1章", "状态": "已埋",
                                           "计划回收": "第40章", "备注": ""}]}, f,
                  ensure_ascii=False)
    ts.advance_foreshadow(proj, 1, ["黑袍人的令牌"])
    assert ts.load_foreshadow(proj)["rows"][0]["状态"] == "推进中"

    new_draft = _draft("这一版重写了祠堂一段。")
    client = _CapturingClient({"prose": [new_draft]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)

    data = ts.load_foreshadow(proj)
    assert data["rows"][0]["状态"] == "已埋", "重写回补：该章推进应撤销回迁出态"
    assert data.get("advances") == [], "该章 advances 日志清零，重定稿可重登记"
    assert any("重写回补：撤销伏笔推进 1 条" in lg for lg in ctx.logs)
    assert len(versions.list_versions(proj, 1)) == 2, "旧稿应归档为整章重写版"


def test_b4_first_finalize_does_not_rollback(tmp_path):
    """首版定稿（无旧稿）不触回补——伏笔推进保持原状"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    with open(os.path.join(proj, "追踪", "伏笔表.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rows": [{"伏笔": "黑袍人的令牌", "类别": "物",
                                           "埋设章节": "第1章", "状态": "推进中",
                                           "计划回收": "第40章", "备注": ""}]}, f,
                  ensure_ascii=False)
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)
    assert ts.load_foreshadow(proj)["rows"][0]["状态"] == "推进中", \
        "非重写路径不许动伏笔状态"
    assert not [lg for lg in ctx.logs if "重写回补" in lg]


# ---------------- 白名单接线：scan_deslop 传 proj ----------------

def test_whitelist_wiring_passes_proj_at_all_call_sites():
    """stages 四个 scan_deslop 调用点全部传 proj（源码钉，防未来解线）"""
    src = open(os.path.join(os.path.dirname(stages.__file__), "stages.py"),
               encoding="utf-8").read()
    n = len(re.findall(r"scan_deslop\(self\.prose, proj=", src))
    assert n == 4, f"stages 内 scan_deslop 应 4 处全部传 proj（实测 {n}）"


def test_whitelist_actually_masks_blocking_phrase(tmp_path):
    """书级白名单行为：命中字面 span 不再出阻断（gates 层行为回归）"""
    proj = str(tmp_path / "白名单书")
    os.makedirs(proj, exist_ok=True)
    prose = "## 第1章\n\n这不是巧合，而是命运的伏笔。"
    blk_plain = gates.scan_deslop(prose)
    assert blk_plain[0], "夹具句必须先真是阻断级（「不是A而是B」翻转句式）"
    with open(os.path.join(proj, ".deslop-whitelist"), "w", encoding="utf-8") as f:
        f.write("# 书级白名单\n这不是巧合\n")
    blk_proj = gates.scan_deslop(prose, proj=proj)
    assert len(blk_proj[0]) < len(blk_plain[0]), "白名单必须减少阻断数"
    assert all("不是巧合" not in str(getattr(f, "text", ""))
               for f in blk_proj[0]), "命中 span 不再出阻断"


# ---------------- E1：prompt 快照接口 ----------------

def test_e1_prompt_snapshots_populated_per_kind(tmp_path):
    """内存快照：prose/deslop/chapter_summary kind 在场且为最终装配 prompt"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    blocking_draft = "## 第1章 开端\n\n" + _BASE * 39 + "这不是巧合，而是命运的伏笔。"
    client = _CapturingClient({"prose": [blocking_draft], "deslop": [_draft()]})
    ctx = _WiringCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)

    snaps = ctx.prompt_snapshots
    assert isinstance(snaps, dict) and snaps, "E1 快照必须产出"
    assert snaps.get("prose"), "草稿轮快照在场"
    assert "本章细纲" in snaps["prose"] or "核心事件" in snaps["prose"]
    assert snaps.get("deslop"), "去味轮快照在场（_rewrite_phase 相位键）"
    assert snaps.get("chapter_summary"), "摘要轮快照在场"
    assert "enrich" not in snaps, "未触发的相位不许留陈旧键（章入口清零纪律）"


def test_e1_snapshot_dump_off_by_default_on_via_config(tmp_path):
    """debug.prompt_snapshot_dir 缺省 off（不落盘）；配置后 <章号>_<kind>.md 落盘"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    dump_dir = str(tmp_path / "snaps")
    cfg = _cfg()
    cfg["debug"] = {"prompt_snapshot_dir": dump_dir}
    client = _CapturingClient({"prose": [_draft()]})
    ctx = _WiringCtx(proj, cfg, client)
    stages.chapter_microcycle(ctx, 1)

    assert os.listdir(dump_dir), "配置后必须落盘"
    p = os.path.join(dump_dir, "001_prose.md")
    assert os.path.exists(p)
    with open(p, encoding="utf-8") as f:
        assert f.read() == ctx.prompt_snapshots["prose"]


def test_e1_dump_disabled_without_debug_key(tmp_path):
    """缺省 off：未配置 debug.prompt_snapshot_dir 时不产生任何落盘"""
    proj = _mk_proj(tmp_path, _legacy_outline)
    off_dir = str(tmp_path / "off_snaps")
    cfg = _cfg()
    cfg["debug"] = {"prompt_snapshot_dir": ""}   # 显式空 = off
    ctx = _WiringCtx(proj, cfg, _CapturingClient())
    ctx.last_prompt = "P"
    stages._snap_prompt(ctx, "prose", 1)
    assert ctx.prompt_snapshots == {"prose": "P"}, "内存快照始终在"
    assert not os.path.exists(off_dir), "off 时不落盘不建目录"
