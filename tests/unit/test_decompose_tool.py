# -*- coding: utf-8 -*-
"""拆解工具单测：专题层（民生与市场）/分块并发/覆盖度报告/现状兼容

tests/decompose_worldbook.py 是脚本（带 Qt/配置装配的 main），这里用 importlib
按路径装载模块，只测纯函数层：LLM 流式调用以假 client 注入（extract_chunk 只吃
client.chat_stream），项目骨架用 tmp_path 手搭（设定/、大纲/、正文/、追踪/）。
"""
import concurrent.futures
import importlib.util
import json
import os
import re
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL_PATH = os.path.join(ROOT, "tests", "decompose_worldbook.py")


def _load_tool():
    spec = importlib.util.spec_from_file_location("decompose_worldbook", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _load_tool()


@pytest.fixture(autouse=True)
def _no_retry_sleep(tool, monkeypatch):
    """退避秒数归零：走重试路径的单测不许真睡 2 秒"""
    monkeypatch.setattr(tool, "RETRY_DELAY", 0.0)


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "同人测试"
    p.mkdir()
    for d in ("设定", "大纲", "正文", "追踪"):
        (p / d).mkdir()
    return str(p)


def _payload(entries=(), rules=()):
    return json.dumps({"entries": list(entries), "rules": list(rules)}, ensure_ascii=False)


class FakeClient:
    """替身 LLMClient.chat_stream：按 prompt 里的块号返回预制 JSON，线程安全地记录调用

    回复按「块号 → 文本」索引（default 兜底），不按调用序——并发下调用顺序不定，
    按块号索引才能让断言确定。
    """

    def __init__(self, by_chunk=None, default=None):
        self.by_chunk = dict(by_chunk or {})
        self.default = default
        self.prompts = []          # [(块号, prompt)]
        self.lock = threading.Lock()

    def chat_stream(self, prompt, system="", temperature=None, on_chunk=None, **kw):
        m = re.search(r"材料（第 (\d+)/", prompt)
        idx = int(m.group(1)) if m else 0
        with self.lock:
            self.prompts.append((idx, prompt))
            out = self.by_chunk.get(idx, self.default)
        if out is None:
            out = "{}"
        if on_chunk:
            on_chunk(out)
        return out


# 三段各 16-20 字，chunk_chars=25 → 恰好切 3 块（整段不拆）
SRC_TEXT = "\n\n".join([
    "乌坦城是加玛帝国边陲小城，城中当铺林立。",
    "斗气大陆以斗气为尊，等级森严不可逾越。",
    "萧炎年轻时在乌坦城受到家族冷遇。",
])


# ==================== ① general 模式产出现状兼容 ====================

def test_general_mode_compat(tool, proj):
    """general 落盘 世界书.md/正则.md/拆解清单.json，归一化同名条目跨块先到先得"""
    client = FakeClient({
        1: _payload(
            entries=[
                {"name": "斗气等级", "cat": "体系规则", "desc": "斗者到斗帝十级，每级九星。",
                 "constant": True, "keys": []},
                {"name": "乌坦城", "cat": "地理", "desc": "加玛帝国边陲小城。",
                 "constant": False, "keys": ["乌坦"]},
            ],
            rules=[{"rule": "斗气等级不可逾越", "level": "must", "pattern": ""}],
        ),
        # 第 2 块重出「乌坦城」（书名号归一化后同名）→ 该版本必须被去重丢掉
        2: _payload(entries=[
            {"name": "《乌坦城》", "cat": "地理", "desc": "重复块里的版本，不该出现。"}]),
        3: _payload(entries=[{"name": "萧炎", "cat": "人物", "desc": "主角。"}]),
    })
    out = tool.run_decompose(proj, client, SRC_TEXT, chunk_chars=25, themes=("general",))
    assert set(out) == {"general"} and out["general"]["chunks"] == 3

    doc = open(os.path.join(proj, "设定", "世界书.md"), encoding="utf-8").read()
    assert "## 世界书" in doc
    assert "### 体系规则" in doc and "### 地理" in doc and "### 人物" in doc
    assert "- **乌坦城**（地理）：加玛帝国边陲小城。" in doc
    assert "[常驻]" in doc, "constant 条目要带 [常驻] 标记"
    assert "重复块里的版本" not in doc, "归一化同名条目应先到先得"
    # 块序确定：乌坦城（第1块）排在萧炎（第3块）前
    assert doc.index("乌坦城") < doc.index("萧炎")

    rx = open(os.path.join(proj, "设定", "正则.md"), encoding="utf-8").read()
    assert "- 规则：斗气等级不可逾越｜level：must｜scope：全文" in rx

    ledger = json.load(open(os.path.join(proj, "追踪", "拆解清单.json"), encoding="utf-8"))
    assert set(ledger) == {"fandom", "entries", "rules", "chunks"}
    assert ledger["chunks"] == 3
    assert [e["name"] for e in ledger["entries"]] == ["斗气等级", "乌坦城", "萧炎"]
    assert len(ledger["rules"]) == 1
    assert os.path.exists(os.path.join(proj, "追踪", "拆解覆盖度.json"))


# ==================== ② 专题模式不碰世界书 ====================

def test_theme_mode_writes_sidecar_ledger_only(tool, proj):
    """民生与市场专题：写 追踪/拆解_专题_*.json（与主清单同构），不自动改世界书.md"""
    open(os.path.join(proj, "设定", "世界书.md"), "w", encoding="utf-8").write("KEEP-WB")
    open(os.path.join(proj, "设定", "正则.md"), "w", encoding="utf-8").write("KEEP-RX")

    payload = _payload(
        entries=[{"name": "铜币", "cat": "民生与市场", "desc": "1金币=10银币=1000铜币，馒头一个三铜币。",
                  "constant": True, "keys": ["铜铢"]}],
        rules=[{"rule": "小额交易一律以铜币结算", "level": "must", "pattern": ""}],
    )
    client = FakeClient(default=payload)   # 3 块同回复 → 跨块去重只剩 1 条
    out = tool.run_decompose(proj, client, SRC_TEXT, chunk_chars=25, themes=("民生与市场",))
    assert set(out) == {"民生与市场"}

    ledger = json.load(open(os.path.join(proj, "追踪", "拆解_专题_民生与市场.json"),
                            encoding="utf-8"))
    assert set(ledger) == {"fandom", "entries", "rules", "chunks"}, "专题清单与主清单同构"
    assert ledger["chunks"] == 3
    assert [e["name"] for e in ledger["entries"]] == ["铜币"], "同名条目跨块去重"
    assert len(ledger["rules"]) == 1

    # 主文件一字不动，主清单也不该出现
    assert open(os.path.join(proj, "设定", "世界书.md"), encoding="utf-8").read() == "KEEP-WB"
    assert open(os.path.join(proj, "设定", "正则.md"), encoding="utf-8").read() == "KEEP-RX"
    assert not os.path.exists(os.path.join(proj, "追踪", "拆解清单.json"))

    # 专题指令确实追加在基础 PROMPT 之后
    assert client.prompts and all(p.startswith("你是网文世界观设定管理员") for _i, p in client.prompts)
    assert any("【专题指令：民生与市场】" in p for _i, p in client.prompts)


# ==================== ③ 覆盖度报告 ====================

def test_coverage_missing_flags_themes(tool, proj, capsys):
    """缺类别判定：只认期望清单内的类别；「民生与市场」缺席 → 红榜建议 --theme 补拆"""
    entries = [{"cat": "体系规则"}, {"cat": " 人物 "}, {"cat": "不在期望清单"}]
    report = tool.coverage_report([entries], proj)

    assert report["categories_present"] == ["体系规则", "人物"]
    assert report["categories_missing"] == [c for c in tool.EXPECTED_CATEGORIES
                                            if c not in ("体系规则", "人物")]
    assert "民生与市场" in report["categories_missing"]
    saved = json.load(open(os.path.join(proj, "追踪", "拆解覆盖度.json"), encoding="utf-8"))
    assert saved == report
    assert "建议 --theme 补拆" in capsys.readouterr().out


def test_coverage_all_present_no_redboard(tool, proj, capsys):
    entries = [{"cat": c} for c in tool.EXPECTED_CATEGORIES]
    report = tool.coverage_report([entries], proj)
    assert report["categories_present"] == tool.EXPECTED_CATEGORIES
    assert report["categories_missing"] == []
    assert "建议 --theme 补拆" not in capsys.readouterr().out


def test_coverage_merges_general_and_theme(tool, proj):
    """--theme all 语义：general + 专题的条目合起来对账（专题补上民生与市场后不再缺）"""
    report = tool.coverage_report([[{"cat": "人物"}], [{"cat": "民生与市场"}]], proj)
    assert report["categories_present"] == ["人物", "民生与市场"]
    assert "民生与市场" not in report["categories_missing"]


# ==================== ④ 并发路径 ====================

def test_concurrent_three_chunks_deterministic(tool, proj, monkeypatch):
    """3 块并发不炸、worker=3、汇合后按块序去重输出确定"""
    seen = {}
    real_executor = concurrent.futures.ThreadPoolExecutor

    class SpyExecutor(real_executor):
        def __init__(self, *a, **kw):
            seen["max_workers"] = kw.get("max_workers", a[0] if a else None)
            super().__init__(*a, **kw)

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", SpyExecutor)

    client = FakeClient({
        1: _payload(entries=[{"name": "甲", "cat": "人物", "desc": "第一块。"}]),
        2: _payload(entries=[{"name": "乙", "cat": "地理", "desc": "第二块。"}]),
        3: _payload(entries=[{"name": "甲", "cat": "人物", "desc": "第三块重名。"}]),
    })
    out = tool.run_decompose(proj, client, SRC_TEXT, chunk_chars=25, themes=("general",))
    assert seen["max_workers"] == 3, "分块抽取固定 3 并发"
    assert len(client.prompts) == 3, "3 块都要被抽取"
    assert {i for i, _p in client.prompts} == {1, 2, 3}
    ledger = json.load(open(os.path.join(proj, "追踪", "拆解清单.json"), encoding="utf-8"))
    assert [e["name"] for e in ledger["entries"]] == ["甲", "乙"], "跨块重名按块序先到先得"
    assert out["general"]["chunks"] == 3


def test_extract_chunk_retries_then_succeeds(tool):
    """单块 3 次重试：前两次坏 JSON，第三次成功"""
    calls = {"n": 0}

    class Flaky:
        def chat_stream(self, prompt, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("坏 JSON")
            return _payload(entries=[{"name": "萧炎", "cat": "人物", "desc": "主角。"}])

    data = tool.extract_chunk(Flaky(), "prompt", delay=0)
    assert calls["n"] == 3
    assert data["entries"][0]["name"] == "萧炎"


def test_extract_chunk_gives_up_after_three_failures(tool, capsys):
    class Always:
        def chat_stream(self, prompt, **kw):
            return "这不是 JSON"

    assert tool.extract_chunk(Always(), "prompt", retries=3, delay=0) is None
    assert "放弃该块" in capsys.readouterr().out


# ==================== CLI 与 prompt 组装 ====================

def test_cli_and_theme_resolution(tool):
    args = tool.parse_args(["P", "1234", "--theme", "all"])
    assert args.proj == "P" and args.chunk_chars == 1234
    assert tool.resolve_themes("all") == ["general", "民生与市场"]
    assert tool.resolve_themes("general") == ["general"]
    assert tool.resolve_themes("民生与市场") == ["民生与市场"]
    defaults = tool.parse_args(["P"])
    assert defaults.chunk_chars == 8000 and defaults.theme == "general"
    assert tool.theme_choices() == ["general", "民生与市场", "all"]


def test_build_prompt_general_unchanged(tool):
    """general 主题的 prompt 与现状 PROMPT 逐字一致；专题只是在后面追加指令"""
    chunk = "材料正文"
    base = tool.PROMPT.format(fandom="斗破苍穹", i=1, n=2, chunk=chunk)
    assert tool.build_prompt("general", "斗破苍穹", 1, 2, chunk) == base
    themed = tool.build_prompt("民生与市场", "斗破苍穹", 1, 2, chunk)
    assert themed.startswith(base + "\n\n")
    assert "【专题指令：民生与市场】" in themed
    assert "辅币" in themed and "税收" in themed and "行会" in themed
