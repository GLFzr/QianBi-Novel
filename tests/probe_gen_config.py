# -*- coding: utf-8 -*-
"""P2 章级快照 + P3 固化为模板探针（不发任何 LLM 请求）

验证链路：世界书装配元信息 → stages 轨迹 → 正文/.annotations/第N.json →
bridge.chapterGenConfig 排版 → Main.qml GenConfigDialog 真渲染（含「未登记」兜底分支）
→ 「固化为模板」落用户预设仓并被加载链读回 → 新建项目的预设下拉真的生效。
"""
import json
import os
import atexit
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 预设要落在临时目录（探针会往用户预设仓写文件）：HOME 重定向后 config/presets 全在沙箱里
FAKE_HOME = tempfile.mkdtemp(prefix="qianbi_gen_probe_")
REAL_HOME = os.path.expanduser("~")
REAL_PRESET_DIR = os.path.join(REAL_HOME, ".qianbi_novel", "presets")
REAL_PRESETS = set(os.listdir(REAL_PRESET_DIR)) if os.path.isdir(REAL_PRESET_DIR) else set()
_real_cfg = os.path.join(REAL_HOME, ".qianbi_novel", "config.json")
os.makedirs(os.path.join(FAKE_HOME, ".qianbi_novel"), exist_ok=True)
if os.path.isfile(_real_cfg):
    shutil.copyfile(_real_cfg, os.path.join(FAKE_HOME, ".qianbi_novel", "config.json"))
os.environ["HOME"] = FAKE_HOME
os.environ["USERPROFILE"] = FAKE_HOME
atexit.register(shutil.rmtree, FAKE_HOME, True)

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app import presets as genre_presets
from app import project
from app.core import stages
from app.core import state as st
from app.presets import user_dir
from app.ui.bridge import Bridge

PROJ = os.path.join(FAKE_HOME, "书", "快照探针")
LOGS = []
WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)


RULE = ("## 规则（数值基准）\n"
        "- **力量体系**（规则）：一至九品，品阶压制绝对；越阶出手必付代价，轻则气血两亏，重则根基崩断。"
        "这一条约束所有打斗场面，写之前先确认双方品阶，写之后再确认代价是否落地，否则视为违规。\n"
        "- **货币基准**（规则）：一两银兑千钱，拍卖行抽三成佣金；灵石只在三品以上流通，凡俗市面见不到。"
        "凡涉及报价的段落，都要与这条基准对齐，前后章不得出现同一件东西价差三倍以上而无解释。\n\n")

CHARS = "## 角色\n" + "".join(
    f"- **{name}**（{kind}）：{desc}此条目用于把世界书撑过注入预算，从而验证逐条激活、触发原因与截断行为，"
    f"而不是整份文件照搬。因此每条都要写得足够长：长到预算必须在条目之间做取舍，长到「这一章到底给了模型哪几条设定」"
    f"成为一个真的需要被记录下来、被看见的问题，而不是一个含糊的「大概都给过了」。\n"
    for name, kind, desc in (
        ("陈更", "主角", "表面是当铺朝奉，实际靠一双能看见物件余温的手断案。"),
        ("柳三更", "对手", "巡夜司百户，办案讲证据也讲人情，与陈更互相利用。"),
        ("孙九", "配角", "当铺伙计，消息灵通但嘴碎，是市井信息的出口。"),
        ("周娘子", "配角", "拍卖行管事，笑里藏刀，只认三成佣金。"),
        ("铁臂李", "配角", "漕帮堂主，三品武者，脾气与臂力成正比。"),
        ("小满", "配角", "药铺学徒，认得百药不认得人，常被拿来验毒。"),
        ("算盘徐", "配角", "账房先生，一口一个数字，从不正面回答问题。"),
        ("白先生", "配角", "私塾先生，城里掌故的活字典，说话爱绕三个弯。"),
        ("崔佛儿", "配角", "丐帮小子，替陈更跑腿，收报酬只收糖。"),
        ("金三爷", "配角", "漕运东家，笑面虎，与拍卖行有旧怨。"),
        ("阿竹", "配角", "药铺掌柜的侄女，识字会算，替小满管账。"),
        ("洛七", "配角", "边地货商，每月过城一次，带来外地的稀罕物件。"),
    )) + "\n"

OUTLINE = ("核心事件：陈更在拍卖行当场识破一件赝品。\n"
           "出场顺序：陈更、周娘子、柳三更\n"
           "情节点：\n"
           "1. 陈更摸到物件上的余温不对。\n2. 周娘子拖延时间。3. 柳三更带人封门。\n")


def build_fixture():
    os.makedirs(os.path.join(FAKE_HOME, "书"), exist_ok=True)
    project.create_project(os.path.join(FAKE_HOME, "书"), "快照探针")
    project.write_file(os.path.join(PROJ, project.WORLDBOOK_PATH), RULE + CHARS)
    project.write_file(os.path.join(PROJ, "大纲", "细纲_第001章.md"), OUTLINE)
    project.write_file(os.path.join(PROJ, "正文", "第001章_鉴宝.md"), "# 第1章 鉴宝\n正文。")
    st.save_state(PROJ, {"stage": "writing", "current_chapter": 1, "total_chapters": 5,
                         "genre_preset": "probe_snap",
                         "history": [{"num": 1, "title": "鉴宝", "words": 3, "status": "pass",
                                      "deslop_blocking": 0, "deslop_advisory": 0, "ts": "T"}]})
    with open(os.path.join(user_dir(), "probe_snap.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "probe_snap", "name": "快照探针预设", "version": 2,
                   "style_hint": "冷硬短句，动词优先",
                   "sampling": {"temperature": 0.8},
                   "stage_params": {"prose": {"temperature": 0.95, "top_p": 0.9, "slot": "写作"}}}, f,
                  ensure_ascii=False)


class _Ctx:
    proj = PROJ

    def log(self, level, msg):
        LOGS.append((level, msg))


class _Client:
    model = "probe-model"
    last_sampling = {"temperature": 0.95, "top_p": 0.9}
    last_degraded = True


def snapshot_via_pipeline_path():
    """走生产函数链：装配元信息 → 轨迹 → 落盘（不另写一份「测试专用」逻辑）"""
    ctx = _Ctx()
    stages.begin_gen_trace(ctx)
    _wb, _rg, meta = stages._wb_rg_blocks(PROJ, {}, 1)
    doc = project.read_file(os.path.join(PROJ, project.WORLDBOOK_PATH))
    assert len(doc) > meta["budget"], (len(doc), meta["budget"])
    assert meta["dropped"], f"世界书未触发取舍（预算 {meta['budget']} 字），探针夹具需要加长"
    assert len(meta["activated"]) >= 2, meta["activated"]
    stages._record_worldbook(ctx, "outline", meta)
    stages._record_worldbook(ctx, "prose", meta)
    stages._record_call(ctx, "prose", "写作", _Client(), "本章 prompt 全文")
    return stages.write_gen_config(ctx, 1)


def find_object(obj, name, out):
    for child in obj.children():
        if child.objectName() == name:
            out.append(child)
        find_object(child, name, out)
    return out


def iter_objects(obj):
    """声明式子节点遍历。注意：Repeater 生成的 delegate 不在 QObject.children() 里
    （实测 count=2 而树中查无），要证明 delegate 渲染了，只能读 count/尺寸。"""
    yield obj
    for child in obj.children():
        yield from iter_objects(child)


def _py(value):
    """QML 里赋的 JS 字面量读回来是 QJSValue，桥返回值是 list/dict"""
    if hasattr(value, "toVariant"):
        return value.toVariant()
    return value


def texts_of(obj, out=None):
    out = [] if out is None else out
    t = obj.property("text")
    if isinstance(t, str) and t:
        out.append(t)
    for child in obj.children():
        texts_of(child, out)
    return out


def _read_qml(rel: str) -> str:
    with open(os.path.join(ROOT, "app", "ui", "qml", rel), encoding="utf-8") as f:
        return f.read()


SNAP = None
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append(ok)
    print(("[OK ] " if ok else "[FAIL] ") + name + ("" if ok else "  << " + extra), flush=True)


app = QGuiApplication([])
build_fixture()
SNAP = snapshot_via_pipeline_path()
check("快照落进 正文/.annotations/第1章.json",
      project.get_chapter_gen_config(PROJ, 1) == SNAP
      and os.path.isfile(os.path.join(PROJ, "正文", ".annotations", "第1章.json")))
check("快照记录了参数档与预设", SNAP["preset"] == "probe_snap"
      and SNAP["sampling"] == {"temperature": 0.8}
      and SNAP["stage_params"]["prose"]["temperature"] == 0.95)

engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
if not engine.rootObjects():
    print("FAIL: Main.qml 加载失败")
    for w in WARNINGS:
        print("  QML>", w)
    sys.exit(1)
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)


def step1_wiring():
    body = "\n".join(texts_of(win))
    check("队列行已实例化（含第 1 章标题）", "鉴宝" in body, body[:400])
    qr = _read_qml(os.path.join("components", "QueueRow.qml"))
    cp = _read_qml("ChapterPanel.qml")
    check("QueueRow 声明 viewGenConfig 信号 + 右键项",
          "signal viewGenConfig(int num)" in qr and '"查看生成配置…"' in qr)
    check("ChapterPanel 把右键项接到 bridge.showGenConfig",
          "onViewGenConfig: function (n) { bridge.showGenConfig(n) }" in cp)
    QTimer.singleShot(150, step2_dialog)


def step2_dialog():
    b.showGenConfig(1)
    QTimer.singleShot(500, step3_read)


def step3_read():
    hits = find_object(win, "genConfigDialog", [])
    check("GenConfigDialog 随 genConfigReady 打开",
          bool(hits) and bool(hits[0].property("visible")), f"hits={len(hits)}")
    if not hits:
        return finish()
    dlg = hits[0]

    # 文案口径在 bridge 层（QML 只排版 section），所以文字断言读 bridge 返回值
    d = b.chapterGenConfig(1)
    body = "\n".join(s["title"] + "\n" + "\n".join(s["lines"])
                     for s in d["sections"]) if d["found"] else ""
    check("快照按相位分节（配置 + 细纲世界书 + 正文世界书 + 调用）",
          d["found"] and len(d["sections"]) == 4,
          f"sections={[s['title'] for s in d['sections']] if d['found'] else d}")
    for needle in ("快照探针预设", "全书采样基线：温度=0.8",
                   "正文档：连接槽=写作 · 温度=0.95 · 核采样=0.9",
                   "细纲世界书 · 激活", "正文世界书 · 激活",
                   "陈更｜", "周娘子｜", "未入预算：", "probe-model",
                   "网关拒收已降级", "调用记录（1 次）"):
        check(f"快照含「{needle}」", needle in body, "实际>>>\n" + body[:1500])
    check("激活原因逐条可读",
          "本章命中" in body or "节权重" in body or "常驻" in body, body[:600])
    check("参数档按预设字段顺序排版（温度不排在槽之前）",
          "连接槽=写作 · 温度=0.95" in body, body[:1500])

    # 真渲染证据：Repeater delegate 在 QObject.children() 里不可见，只能读 count 与高度
    check("有快照时才暴露「固化为模板」入口", bool(dlg.property("hasSnapshot")))
    reps = [r for r in iter_objects(dlg) if "Repeater" in r.metaObject().className()]
    check("外层 Repeater 已实例化 4 个 section delegate",
          bool(reps) and max(int(r.property("count") or 0) for r in reps) == 4,
          f"counts={[r.property('count') for r in reps]}")
    bodies = find_object(win, "genConfigBody", [])
    h = float(bodies[0].property("implicitHeight") or 0) if bodies else 0.0
    check("正文区按内容撑开（可滚动，不是空壳）", h > 300, f"implicitHeight={h}")
    QTimer.singleShot(200, step4_legacy)


def step4_legacy():
    b.showGenConfig(2)          # 第 2 章从未生成 → 兜底文案
    QTimer.singleShot(500, step5_read_legacy)


def step5_read_legacy():
    hits = find_object(win, "genConfigDialog", [])
    secs = _py(hits[0].property("sections")) or [] if hits else []
    body = "\n".join([s.get("title", "") for s in secs] +
                     [l for s in secs for l in s.get("lines", [])])
    check("无快照章节走「未登记」兜底（不再显示空表）",
          bool(hits) and len(secs) == 1 and "没有生成配置记录" in body, body[:400])
    check("兜底分支仍显示章号", "第 2 章" in body, body[:400])
    check("兜底分支 bridge 报 found=False", not b.chapterGenConfig(2)["found"])
    check("无快照时收起「固化为模板」入口", not bool(hits[0].property("hasSnapshot")))
    QTimer.singleShot(150, step6_p3_template)


def step6_p3_template():
    """P3 飞轮回路：这一章的参数 → 可复用预设 → 加载链读回来还是它"""
    r = b.saveChapterPresetTemplate(1)
    check("固化成功并落进用户预设仓",
          r["ok"] and os.path.isfile(os.path.join(user_dir(), r["id"] + ".json")), str(r))
    check("模板 id 带 snap_ 前缀且不含中文",
          r["id"].startswith("snap_") and r["id"].isascii(), r["id"])
    sp = genre_presets.stage_params(r["id"])
    check("模板读回来就是当时生效的相位档",
          sp["prose"]["temperature"] == 0.95 and sp["prose"]["slot"] == "写作", str(sp))
    check("模板全书基线沿用快照采样",
          genre_presets.sampling(r["id"]).get("temperature") == 0.8,
          str(genre_presets.sampling(r["id"])))
    check("模板出现在预设库下拉数据源里",
          r["id"] in [i["id"] for i in b.genrePresets()], str(b.genrePresets())[:300])
    saved = json.load(open(os.path.join(user_dir(), r["id"] + ".json"), encoding="utf-8"))
    check("模板冻结完整配方：题材文本块随来源预设一起带走",
          saved.get("style_hint") == "冷硬短句，动词优先"
          and "快照探针预设" in saved.get("description", ""), str(saved)[:400])
    check("模板不落加载器路径标记", not any(k.startswith("_") for k in saved), str(saved)[:200])
    again = b.saveChapterPresetTemplate(1)
    check("重复固化只覆盖同一模板", again["ok"] and again["id"] == r["id"]
          and again["updated"] and len([f for f in os.listdir(user_dir())
                                        if f.startswith("snap_")]) == 1, str(again))
    bad = b.saveChapterPresetTemplate(2)
    check("无快照章节拒绝固化", not bad["ok"] and "快照" in bad["msg"], str(bad))
    check("QML 静态接线：对话框按钮 + 书架传 presetId",
          'text: "固化为模板"' in _read_qml(os.path.join("components", "GenConfigDialog.qml"))
          and "it ? it.id" in _read_qml("BookshelfPanel.qml"))
    QTimer.singleShot(150, lambda: step7_p3_newproject(r["id"]))


def step7_p3_newproject(pid):
    """修断链：新建项目选的题材预设此前从不进 newProject"""
    root = os.path.join(FAKE_HOME, "新书")
    os.makedirs(root, exist_ok=True)
    ok = b.newProject(root, "P3接线书", "都市", "番茄", 20, "一支能改命的笔", pid)
    path = os.path.join(root, "P3接线书")
    check("newProject 接收并写入 presetId",
          ok and st.load_state(path).get("genre_preset") == pid,
          str(st.load_state(path).get("genre_preset")))
    check("新书的预设确实带回了那套相位档",
          genre_presets.stage_params(b.projectPreset())["prose"]["slot"] == "写作")
    plain = b.newProject(root, "无预设书", "都市", "番茄", 20, "灵感")
    check("不选预设时保持旧行为（genre_preset 为空）",
          plain and st.load_state(os.path.join(root, "无预设书")).get("genre_preset", "") == "")
    QTimer.singleShot(200, finish)


def finish():
    if finish.done:
        return
    finish.done = True
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w
            or "is not defined" in w]
    check("无 QML ReferenceError/TypeError", not errs, "\n".join(WARNINGS[:10]))
    now = set(os.listdir(REAL_PRESET_DIR)) if os.path.isdir(REAL_PRESET_DIR) else set()
    check("真实用户预设仓零改动（模板只落沙箱）", now == REAL_PRESETS,
          f"多出 {sorted(now - REAL_PRESETS)} / 少掉 {sorted(REAL_PRESETS - now)}")
    print("PROBE_DONE " + ("FAIL" if (False in RESULTS) else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


finish.done = False


def watchdog():
    if finish.done:
        return
    check("探针在时限内跑完", False, "某步骤抛异常或未推进（见上方最后一条 OK）")
    finish()


QTimer.singleShot(600, step1_wiring)
QTimer.singleShot(45000, watchdog)
sys.exit(app.exec())
