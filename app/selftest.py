# -*- coding: utf-8 -*-
"""打包态一致性自检（发版门禁）

要解决的问题：打包冒烟只证明「窗口出现 + 存活 5s」，证明不了「打包后的程序实现原程序
的所有效果」。真实漏口——某个发行包里少了本轮新增的一个 `.qml`（整件功能缺失），
而流水线照样绿。

开发态与打包态各跑一遍，产出的 JSON 由 `tests/probe_packaged.py` 逐字段对拍：

    QianBi-Novel.exe --selftest <out.json>      # 打包态（run.py 在 import app.main 前拦截）
    python -m app.selftest --out <out.json>     # 开发态

四段摘要可单跑（`--only imports,manifest`）：
- imports  ：关键模块能不能 import（打包后 keyring 后端退化在这里现形，而不是变成行为差异）
- manifest ：随包分发的资源文件逐文件 sha256（少一个 .qml / 预设 json 立刻红）
- assembly ：真实装配/扫描/payload 函数在固定夹具上的输出摘要（同码不同效也抓得到）
- qml      ：offscreen 真装载 Main.qml + 真 Bridge，报对象在位情况与 QML 接线错误

纪律（改本文件前必读）：
1. **导入任何 app 模块之前**先重定向 HOME/USERPROFILE——`config.py`、`presets`、`crash.py`、
   `usage.py`、`telemetry.py`、`logger.py` 都在模块导入期用 `expanduser("~")` 算常量，
   `QIANBI_CONFIG_DIR` 只护住 config 一个；不隔离就会加载用户真书并回写真配置。
2. 零网络、零 LLM 调用、不依赖 cwd（两侧 cwd 不同：仓库根 vs exe 目录）。
3. 输出里的路径必须经 `_canon()` 归一化，否则两侧永远对不上。
4. 收尾用 `os._exit`：Qt 静态析构会在退出时抛 0xC0000409，把已经写好结果的进程变成非零退出码。
"""
import hashlib
import json
import os
import sys
import tempfile

SECTIONS = ("imports", "manifest", "assembly", "qml")

# ---- 关键导入目标：缺一个就是打包事故 ----
_IMPORT_TARGETS = [
    "httpx", "keyring.backends.Windows",
    "app.wb", "app.core.scan", "app.core.stages", "app.core.gates", "app.core.memory",
    "app.prompts.scene_cards", "app.presets", "app.llm.client", "app.importdoc",
    "app.update_check", "app.ui.bridge",
]

# ---- 资源清单范围：datas 收了什么就比什么；None 表示该目录下全部文件 ----
_MANIFEST_SPECS = [
    ("app/ui/qml", (".qml", "")),      # qmldir 无扩展名
    ("app/presets", (".json",)),
    ("assets", None),
]

# ---- QML 消息过滤：只留「接线断了」的信号，滤掉字体/平台/尺寸等环境噪声 ----
_QML_ERROR_KEYS = ("ReferenceError", "TypeError", "is not defined", "Cannot assign",
                   "is not a member", "is not installed", "Module does not exist")

_QML_OBJECTS = ["panelStack", "forceLockDialog", "genConfigDialog", "genConfigBody",
                "exportDialog", "needsFixDialog", "reviewIssueDialog",
                "importDialog", "importBatchCard", "contractRuleList"]

# ================= 夹具（固定字面量：两侧必须喂同一批字节） =================

_FIXTURE_GENRE = "都市悬疑"
_FIXTURE_PRESET = "urban_destiny"
_FIXTURE_IDEA = "主角的笔记本能改写已经发生的事，代价是忘掉等价的日子。"

_FIXTURE_CORE = """# 核心设定
- 题材：都市悬疑
- 主角：陈更
- 金手指：改写账本
- 主要角色表
- 陈更：当铺学徒
- 柳三更：掌柜之女
"""

_FIXTURE_VOLUME = """# 大纲
### 第1卷 清账（第1-10章）
- 卷契约：陈更用第一次改写换来父亲的清白
"""

_FIXTURE_WB = """# 世界书

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

## 追加登记

- **第九指**（道具）：可替持有者承担一次改写代价 ｜ 首见第2章
- **清账规则**（规则）：子时清账时不能说谎，违者当日记忆归零 ｜ 首见第2章
"""

_FIXTURE_RG = """# 正则约束

- 规则：不得出现「仿佛」「似乎」等推测性比喻｜level：must｜scope：prose
- 规则：每章至少一处具体价钱或数字，且不重复使用同一金额
  续行示例：灵石、时薪、当票面额均可。
"""

_FIXTURE_SUMMARIES = """# 章节摘要

- 第1章：陈更典当三日记忆，柳三更查账发现缺口。
- 第2章：第九指第一次替陈更挡下代价。
"""

# L0 预检与去味扫描的固定样本：含专名错写、数字失配、推测性比喻、AI 腔
_FIXTURE_PROSE = (
    "陈更把当票压在柜台上，柳三庚没有抬头。他想起父亲说过，清账的时候仿佛不能说谎。\n\n"
    "子时的灯灭了三次，账本上多出一行不属于任何人的字。这不仅仅是一张当票，"
    "更是命运的齿轮在他心里缓缓转动。他感到一丝说不上来的滋味涌上心头。\n\n"
    "当票面额是三百两，与第 1 章记的两百两对不上。\n")
_FIXTURE_PREV = "上一章结尾：柳三更没有抬头，只是把账本推回去。\n"


def _fixture_outline(n: int) -> str:
    return (f"### 第{n}章 第{n}章章名\n"
            f"- 章名：第{n}章章名\n"
            f"- 核心事件：陈更在第{n}次清账夜改写当票\n"
            f"- 出场顺序：陈更、柳三更\n"
            f"- 故事内容：陈更典当三日记忆，柳三更查账发现缺口\n"
            f"- 资源收支：余额 -3 天\n"
            f"- 字数：3000\n"
            f"- 章末钩子：当票上多出第三个指印\n")


# 工艺卡路由的四类细纲写法（分别命中 爽点/战斗/谜团/默认留白）
_CRAFT_OUTLINES = [
    ("payoff", "当票摊开，众人方才看清那是掌柜本人的卖身契，满堂哗然，陈更一句话没有说。"),
    ("battle", "擂台之上，柳三更的短刀压住陈更手腕，三招之内胜负已分。"),
    ("mystery", "账本里夹着一张不属于任何一年的当票，笔迹是陈更自己的。"),
    ("plain", "清账夜的灯灭了三次，当铺里没有一个人说话。"),
]

# 自检用预设：worldbook_budget 覆盖装配预算，验证分相位预算真的生效
_FIXTURE_WB_PRESET = {
    "name": "自检预设",
    "worldbook_budget": {"*": 1800, "prose": 900, "outline": 400},
    "style_hint": "冷硬短句，动词优先",
    "taboos": "不得出现推测性比喻",
}

# LLM 请求体自检：显式 stub 档位，不发任何真请求
_FIXTURE_STAGE_PARAMS = {
    "prose": {"temperature": 0.95, "top_p": 0.9, "slot": "写作"},
    "review": {"temperature": 0.7, "max_tokens": 2048},
    "outline": {"temperature": 0.6},
}


# ================= 归一化 =================

_SUBS = []


def _norm(text: str) -> str:
    for src, dst in _SUBS:
        if src and src in text:
            text = text.replace(src, dst)
    return text


def _canon(obj):
    """递归归一化：字符串里的临时目录/资源根一律换成占位符"""
    if isinstance(obj, str):
        return _norm(obj)
    if isinstance(obj, list):
        return [_canon(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in obj.items()}
    return obj


def _body(value) -> str:
    return value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str)


def _entry(id_: str, value) -> dict:
    body = _body(value)
    return {"id": _norm(id_), "chars": len(body),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def _resource_dir(rel: str = "") -> str:
    """兼容开发态（仓库根）与打包态（sys._MEIPASS == _internal）"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS",
                       os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *rel.split("/")) if rel else base


# ================= 四段 =================

def _sec_imports() -> dict:
    import importlib
    out = {}
    for name in _IMPORT_TARGETS:
        try:
            importlib.import_module(name)
            out[name] = "ok"
        except Exception as e:  # noqa: BLE001
            out[name] = "FAIL %s: %s" % (type(e).__name__, e)
    try:
        import keyring
        backend = keyring.get_keyring()
        out["keyring_backend"] = type(backend).__name__
        # 打包后常见退化：Windows 后端丢了 → 落到 Fail*Keyring（读写密钥全废，但导入不报错）
        out["keyring_writable"] = not type(backend).__name__.startswith("Fail")
    except Exception as e:  # noqa: BLE001
        out["keyring_backend"] = "FAIL %s: %s" % (type(e).__name__, e)
        out["keyring_writable"] = False
    return {"targets": out,
            "failed": sorted(k for k, v in out.items()
                             if isinstance(v, str) and v.startswith("FAIL"))}


def _sec_manifest() -> dict:
    entries, missing = [], []
    for rel_dir, allow in _MANIFEST_SPECS:
        base = _resource_dir(rel_dir)
        if not os.path.isdir(base):
            missing.append(rel_dir)
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(d for d in dns if d != "__pycache__")
            for fn in sorted(fns):
                ext = os.path.splitext(fn)[1].lower()
                if ext in (".pyc", ".pyo") or (allow is not None and ext not in allow):
                    continue
                full = os.path.join(dp, fn)
                rel = "%s/%s" % (rel_dir, os.path.relpath(full, base).replace("\\", "/"))
                try:
                    with open(full, "rb") as f:
                        data = f.read()
                except OSError as e:
                    entries.append({"path": rel, "error": str(e)})
                    continue
                entries.append({"path": rel, "bytes": len(data),
                                "sha256": hashlib.sha256(data).hexdigest()})
    entries.sort(key=lambda e: e["path"])
    return {"count": len(entries), "missing_dirs": missing, "files": entries}


def _build_fixture(project, tag: str) -> str:
    """临时目录里造一本输入完全固定的夹具书（tag 隔开，多段各用各的）"""
    from app.core import state as st
    root = os.path.join(os.environ["HOME"], "书柜_" + tag)
    os.makedirs(root, exist_ok=True)
    proj = project.create_project(root, "打包自检_" + tag)
    project.write_idea_info(proj, _FIXTURE_GENRE, "番茄", _FIXTURE_IDEA, 30)
    project.ensure_tracking_files(proj)
    st.save_state(proj, {"genre_preset": _FIXTURE_PRESET, "total_chapters": 10,
                         "current_chapter": 3})
    project.write_file(os.path.join(proj, "设定", "题材定位.md"), _FIXTURE_CORE)
    project.write_file(os.path.join(proj, "大纲", "大纲.md"), _FIXTURE_VOLUME)
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), _FIXTURE_WB)
    project.write_file(os.path.join(proj, project.REGEX_PATH), _FIXTURE_RG)
    project.write_file(os.path.join(proj, "追踪", "章节摘要.md"), _FIXTURE_SUMMARIES)
    for n in (1, 2, 3):
        project.write_file(project.get_outline_path(proj, n), _fixture_outline(n))
    project.write_file(project.get_chapter_path(proj, 1, "雨夜清账"),
                       "# 第1章 雨夜清账\n\n" + _FIXTURE_PROSE)
    return proj


def _sec_assembly() -> list:
    from app import config as cfg_mod
    from app import presets as genre_presets
    from app import mustscan, project, wb
    from app.core import gates, scan
    from app.core import stages
    from app.llm.client import LLMClient
    from app.prompts import scene_cards

    cfg_mod.load_config()          # 走一遍真实配置读路径（落在临时 HOME，不碰用户）
    proj = _build_fixture(project, "asm")
    out = []

    # —— 世界书装配内核：章号 × 预算 × 相位（预设覆盖预算）——
    for num in (0, 1, 3):
        for budget in (2000, 900, 160):
            for phase in ("", "prose", "outline"):
                r = wb.assemble(proj, num, budget, preset=_FIXTURE_WB_PRESET, phase=phase)
                out.append(_entry("wb.assemble num=%s budget=%s phase=%s" % (num, budget, phase),
                                  {"text": r["text"], "activated": r["activated"],
                                   "dropped": r["dropped"], "budget": r["budget"]}))
        for budget in (900, 160):
            anchors = project.worldbook_anchors(proj, num)
            r = wb.assemble(proj, num, budget, anchors=anchors)
            out.append(_entry("wb.assemble.anchors num=%s budget=%s" % (num, budget),
                              {"anchors": anchors, "text": r["text"],
                               "activated": r["activated"], "dropped": r["dropped"]}))

    # —— 世界书/正则直读口（project 层向后兼容签名）——
    for budget in (2000, 600, 160):
        out.append(_entry("project.worldbook_text budget=%s num=2" % budget,
                          project.worldbook_text(proj, budget,
                                                 anchors=project.worldbook_anchors(proj, 2),
                                                 num=2)))
    for sem in ("logic", "regex"):
        out.append(_entry("project.regex_rules %s" % sem, project.regex_rules(proj, sem)))
        for cap in (1500, 120):
            out.append(_entry("project.regex_block %s cap=%s" % (sem, cap),
                              project.regex_block(proj, sem, cap)))
        out.append(_entry("project.regex_block %s must-only cap=120" % sem,
                          project.regex_block(proj, sem, 120, levels=("must",))))

    # —— 正则 must 契约确定性检查（app/mustscan）——
    # 夹具 正则.md 两条都是自然语言（无 pattern），拿它跑只能证明不崩；
    # 这里用显式 pattern 规则，把 forbid 命中 / require 缺失 / 不可编译三条判定路径都覆盖。
    _MUST_RULES = [
        {"rule": "禁止三连感叹", "level": "must", "scope": "全书",
         "pattern": "!{3,}", "mode": "forbid"},
        {"rule": "必须出现具体金额", "level": "must", "scope": "全书",
         "pattern": r"\d+元", "mode": "require"},
        {"rule": "写坏的模式", "level": "must", "scope": "全书",
         "pattern": "(((", "mode": "forbid"},
        {"rule": "自然语言规则不可机判", "level": "must", "scope": "全书",
         "pattern": "", "mode": "forbid"},
    ]
    for label, probe in (("命中", "他付了三十元，走了。!!!"),
                         ("干净", "他付了 30 元，走了。")):
        out.append(_entry("mustscan.check_patterns %s" % label,
                          mustscan.check_patterns(probe, _MUST_RULES)))

    # —— 外部文档导入拆解（app/importdoc）：annotate 只算不写盘，可安全进自检 ——
    _IMP_SRC = ("当铺收的不是东西，是时间。当票上写的期限一过，物归原主，人归回。\n\n"
                "主角不得凭空变强，每次改命必须索回等价代价。")
    _IMP_DOC = ("===核心设定===\n"
                "当铺收的不是东西，是时间。当票上写的期限一过，物归原主，人归回。\n\n"
                "===正则===\n- 主角不得凭空变强，每次改命必须索回等价代价\n"
                "引证：主角不得凭空变强，每次改命必须索回等价代价\n\n"
                "===正文 第7章===\n这一段是模型自己编的，原文里根本没有这句话。\n\n"
                "===大纲===\n（无）\n")
    from app import importdoc as _imp
    out.append(_entry(
        "importdoc.annotate",
        [{"key": p["key"], "num": p["num"], "target": p["target"], "chars": p["chars"],
          "trust": p["trust"], "verbatim": p["verbatim"], "quotes": p["quotesOk"]}
         for p in _imp.annotate(
             _imp.merge_items([_imp.parse_product(_IMP_DOC)]), _IMP_SRC, proj)]))

    # —— 流水线与共写共用的注入内核 ——
    for sem in ("logic", "regex"):
        for num in (0, 2):
            text, rg, meta = stages._wb_rg_blocks(
                proj, {"writing": {"regex_semantics": sem}}, num)
            out.append(_entry("stages._wb_rg_blocks %s num=%s" % (sem, num),
                              {"wb": text, "regex": rg, "meta": meta}))

    # —— 工艺卡：四类细纲路由 × 三章号（轴变体随章号走）——
    for label, outline in _CRAFT_OUTLINES:
        for num in (1, 2, 3):
            out.append(_entry("scene_cards.craft_block %s num=%s" % (label, num),
                              scene_cards.craft_block(num, 10, outline, "")))
    out.append(_entry("scene_cards.chapter_to_cards",
                      [list(scene_cards.chapter_to_cards(o, "")) for _k, o in _CRAFT_OUTLINES]))

    # —— 题材预设块：内置 id 用磁盘 json 清单（发现式列举会受用户预设残留影响）——
    builtin_dir = _resource_dir("app/presets")
    for pid in sorted(f[:-5] for f in os.listdir(builtin_dir) if f.endswith(".json")):
        for stage, _label in genre_presets.STAGE_HINT_KEYS:
            out.append(_entry("presets.genre_block_for %s/%s" % (pid, stage),
                              genre_presets.genre_block_for(pid, stage)))
        out.append(_entry("presets.stage_params %s" % pid, genre_presets.stage_params(pid)))
        out.append(_entry("presets.sampling %s" % pid, genre_presets.sampling(pid)))

    # —— L0 确定性预检与字数闸门（审核链的本地半边，零 LLM）——
    roster = ["陈更", "柳三更"]
    report = scan.scan_chapter(_FIXTURE_PROSE, _FIXTURE_PREV, roster,
                               "第1章：余额 -3 天", ["仿佛"])
    out.append(_entry("scan.scan_chapter", report))
    for cap in (600, 120):
        out.append(_entry("scan.format_scan_block cap=%s" % cap,
                          scan.format_scan_block(report, cap)))
    for quote in ("陈更把当票压在柜台上", "他想起父亲说过，清账的时候仿佛不能说谎", "不存在的引证"):
        out.append(_entry("scan.verify_quote %s" % quote[:8],
                          scan.verify_quote(_FIXTURE_PROSE, quote)))
    for target in (3000, 60, 100):
        out.append(_entry("gates.check_word_bounds target=%s" % target,
                          gates.check_word_bounds(_FIXTURE_PROSE, target)))
    out.append(_entry("gates.scan_deslop", gates.scan_deslop(_FIXTURE_PROSE)))

    # —— LLM 请求体：11 相位 + 审校温度锁 + 无相位基线 + 显式覆盖 ——
    messages = [{"role": "system", "content": "自检系统提示"},
                {"role": "user", "content": "自检用户提示"}]
    phases = [p for p, _label in genre_presets.STAGE_PARAM_PHASES] + ["", "unknown_phase"]
    client = LLMClient(base_url="https://selftest.invalid/v1", api_key="selftest-stub",
                       model="selftest-model", temperature=0.7, max_tokens=4096,
                       stage_params=dict(_FIXTURE_STAGE_PARAMS))
    for stream in (False, True):
        for phase in phases:
            out.append(_entry("LLMClient._build_payload stream=%s phase=%s" % (stream, phase),
                              client._build_payload(messages, stream=stream, phase=phase)))
        for phase in ("prose", "review"):
            out.append(_entry("LLMClient._build_payload explicit stream=%s phase=%s"
                              % (stream, phase),
                              client._build_payload(messages, stream=stream, phase=phase,
                                                    temperature=0.1, max_tokens=777,
                                                    thinking="enabled",
                                                    reasoning_effort="high")))

    out.append(_entry("project.get_chapter_gen_config 1（未登记兜底）",
                      project.get_chapter_gen_config(proj, 1)))
    out.sort(key=lambda e: e["id"])
    return out


def _walk_names(obj, counter):
    name = obj.objectName()
    if name:
        counter[name] = counter.get(name, 0) + 1
    for child in obj.children():
        _walk_names(child, counter)
    return counter


def _sec_qml() -> dict:
    from PySide6.QtCore import QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    from app import project
    from app.ui.bridge import Bridge

    qml_dir = _resource_dir("app/ui/qml")
    noisy = []

    def _capture(mode, ctx, text):
        if any(k in text for k in _QML_ERROR_KEYS):
            noisy.append("|".join([getattr(mode, "name", str(int(mode))),
                                   ctx.file or "", str(getattr(ctx, "line", 0)), text]))

    handler = qInstallMessageHandler(_capture)
    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    engine = QQmlApplicationEngine()
    bridge = Bridge()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.addImportPath(qml_dir)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    root_ok = bool(engine.rootObjects())
    app.processEvents()      # 跑一轮事件循环，让 Component.onCompleted 里的桥回调用完

    report = {"root_ok": root_ok, "qml_dir_exists": os.path.isdir(qml_dir)}
    if root_ok:
        counter = _walk_names(engine.rootObjects()[0], {})
        report["objects"] = {name: counter.get(name, 0) for name in _QML_OBJECTS}
        report["bridge"] = [
            _entry("bridge.genrePresets", bridge.genrePresets()),
            _entry("bridge.chapterGenConfig 1", bridge.chapterGenConfig(1)),
        ]
        proj = _build_fixture(project, "qml")
        bridge._open_project(proj, silent=True)
        report["bridge"] += [
            _entry("bridge.readerChapterList", bridge.readerChapterList()),
            _entry("bridge.needsFixChapters", bridge.needsFixChapters()),
            _entry("bridge.chapterGenConfig 1 夹具书", bridge.chapterGenConfig(1)),
        ]
    qInstallMessageHandler(handler)
    report["errors"] = sorted(set(_norm(x) for x in noisy))
    return report


# ================= 入口 =================

def run(out_path: str = "-", sections=SECTIONS) -> int:
    # 第一件事：任何 app 模块导入之前把 home 换到沙箱（见模块 docstring 纪律 1）
    home = tempfile.mkdtemp(prefix="qianbi_selftest_")
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    root = _resource_dir()
    global _SUBS
    _SUBS = []
    for dst, base in (("<HOME>", home), ("<ROOT>", root)):
        parent = os.path.dirname(base) or base
        for src in (base, parent):
            _SUBS.append((src, dst))
            _SUBS.append((src.replace("\\", "/"), dst))

    report, rc = {}, 0
    for name in sections:
        try:
            report[name] = {"imports": _sec_imports, "manifest": _sec_manifest,
                            "assembly": _sec_assembly, "qml": _sec_qml}[name]()
        except Exception as e:  # noqa: BLE001
            report[name] = {"fatal": "%s: %s" % (type(e).__name__, _norm(str(e)))}
            rc = 1

    report = _canon(report)
    for section in report.values():
        if not isinstance(section, dict):
            continue
        if section.get("fatal") or section.get("failed") or section.get("missing_dirs") \
                or section.get("errors") or section.get("root_ok") is False:
            rc = 1

    text = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True)
    if out_path in ("-", ""):
        sys.stdout.write(text + "\n")
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return rc


def main(argv) -> int:
    out, sections, i = "-", list(SECTIONS), 0
    def _val(name):
        # --only=X / --out=X 形式自带值，否则取下一个 argv
        nonlocal i
        if "=" in name:
            return name.split("=", 1)[1]
        i += 1
        return argv[i] if i < len(argv) else ""

    while i < len(argv):
        a = argv[i]
        if a == "--selftest":
            pass
        elif a in ("--out", "-o") or a.startswith("--out="):
            out = _val(a) or out
        elif a == "--only" or a.startswith("--only="):
            picked = [s for s in _val(a).split(",") if s in SECTIONS]
            sections = picked or sections
        elif not a.startswith("-"):
            out = a        # 打包态用法：`QianBi-Novel.exe --selftest <out.json>`
        i += 1
    return run(out, tuple(sections))


def entry(argv) -> None:
    """命令行唯一入口：写完结果就 os._exit，不给 Qt 静态析构的机会（纪律 4）"""
    code = main(argv)
    try:
        sys.stdout.flush()   # console=False 的 exe 里 stdout 可能不存在
    except Exception:  # noqa: BLE001
        pass
    os._exit(code)


if __name__ == "__main__":
    entry(sys.argv[1:])
