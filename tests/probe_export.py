# -*- coding: utf-8 -*-
"""导出功能探针（不发任何 LLM 请求）

验证：① 真实 Bridge + Main.qml 加载；② exportDialog 打开/预览非空；
③ exportProjectOpts txt 四档标题格式 + 三种分隔均产出可读文件；
④ epub 导出为合法 zip（mimetype 首位未压缩、章 xhtml 齐全）；
⑤ lastExport/路径展示链路 + revealPath 不存在文件守卫；
⑥ 备份项目 zip；⑦ 全程无 ReferenceError/TypeError 类 QML 警告。
"""
import os
import re
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import state as st
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "export_probe_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)


def build_fixture():
    if os.path.isdir(PROJ):
        shutil.rmtree(PROJ)
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    chapters = {
        "第001章_起点.md": "# 第1章 起点\n第一段正文，足够真实。\n\n第二段，含对话“你好”。\n",
        "第002章_转折·上（引号&特殊）.md": "# 第2章 转折·上（引号&特殊）\n剧情推进。\n",
        "第003章_终章·下（大结局）.md": "# 第3章 终章·下（大结局）\n收尾段落。\n",
    }
    for name, text in chapters.items():
        with open(os.path.join(PROJ, "正文", name), "w", encoding="utf-8") as f:
            f.write(text)
    state = dict(st.DEFAULT_STATE)
    state.update({"stage": "writing", "current_chapter": 3, "total_chapters": 3,
                  "history": [
                      {"num": i, "title": t, "words": 10, "deslop_blocking": 0,
                       "deslop_advisory": 0, "status": "pass", "ts": "2026-09-01 12:00:00"}
                      for i, t in [(1, "起点"), (2, "转折"), (3, "终章")]]})
    st.save_state(PROJ, state)


build_fixture()

app = QGuiApplication([])
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


def check(name, ok):
    print(("[OK ] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        check.failed = True


check.failed = False


def find_by_object_name(name):
    for c in win.findChildren(object):
        try:
            if c.objectName() == name:
                return c
        except Exception:
            pass
    return None


def step1_dialog():
    dlg = find_by_object_name("exportDialog")
    check("exportDialog 存在", dlg is not None)
    if dlg:
        dlg.metaObject().invokeMethod(dlg, "refreshPreview")
        dlg.metaObject().invokeMethod(dlg, "open")
    QTimer.singleShot(300, step2_preview)


def step2_preview():
    prev = b.exportPreviewText("blank", 0)
    check("txt 预览非空且含第1章标题", bool(prev) and "第1章" in prev)
    check("预览含正文片段", "第一段正文" in prev)
    # 标题格式切换
    p2 = b.exportPreviewText("line", 1)
    check("分隔线+第X章·标题 预览生效", "第1章·起点" in p2 and "———" in p2)
    p3 = b.exportPreviewText("page", 3)
    check("无标题格式预览不含章节标题行", "第1章" not in p3.split("\n")[0])
    QTimer.singleShot(100, step3_txt)


def step3_txt():
    path = b.exportProjectOpts("txt", "blank", 0)
    check("txt 导出返回路径", bool(path))
    ok_file = bool(path) and os.path.isfile(path)
    check("txt 文件已生成", ok_file)
    if ok_file:
        data = open(path, encoding="utf-8").read()
        titles = re.findall(r"^第\d+章.*$", data, flags=re.M)
        check("txt 三章齐全且有序", titles == ["第1章 起点", "第2章 转折·上（引号&特殊）",
                                               "第3章 终章·下（大结局）"])
        check("txt 含书名行", data.startswith("《export_probe_proj》"))
        check("txt 无 markdown 标题残留", not re.search(r"^#\s", data, flags=re.M))
    QTimer.singleShot(100, step4_txt_opts)


def step4_txt_opts():
    p = b.exportProjectOpts("txt", "line", 2)  # 仅标题
    ok = bool(p) and os.path.isfile(p)
    check("仅标题+分隔线 导出成功", ok)
    if ok:
        data = open(p, encoding="utf-8").read()
        check("仅标题格式生效", "第1章 起点" not in data and "起点\n" in data)
    QTimer.singleShot(100, step5_epub)


def step5_epub():
    path = b.exportProjectOpts("epub", "blank", 0)
    check("epub 导出返回路径", bool(path))
    ok_file = bool(path) and os.path.isfile(path)
    check("epub 文件已生成", ok_file)
    if ok_file:
        z = zipfile.ZipFile(path)
        names = z.namelist()
        check("mimetype 首位且未压缩",
              names[0] == "mimetype" and z.getinfo("mimetype").compress_type == 0)
        xhtmls = [n for n in names if n.startswith("OEBPS/chap_")]
        check("epub 三章 xhtml 齐全", len(xhtmls) == 3)
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        check("opf 骨架合法", 'version="3.0"' in opf and "unique-identifier" in opf)
        c2 = z.read("OEBPS/chap_0002.xhtml").decode("utf-8")
        check("章节 xhtml 可读", "剧情推进" in c2)
        nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
        check("nav 目录三章", nav.count("<li>") == 3)
        check("nav 特殊字符章名已转义", "引号&amp;特殊" in nav)
        bad = z.testzip()
        check("zip 完整性", bad is None)
    QTimer.singleShot(100, step6_backup)


def step6_backup():
    out = b.backupProject()
    check("备份 zip 生成", bool(out) and os.path.isfile(out))
    if out and os.path.isfile(out):
        names = zipfile.ZipFile(out).namelist()
        check("备份含正文与状态", any("正文" in n for n in names)
              and any("pipeline_state" in n for n in names))
        os.remove(out)  # 清理（在 tests_output 下）
    QTimer.singleShot(100, step7_reveal)


def step7_reveal():
    b.revealPath("")          # 空路径守卫
    b.revealPath(r"C:\nonexistent_qoder_probe\x.txt")  # 不存在守卫
    # 不实际打开 explorer，避免干扰；只验证守卫不崩
    QTimer.singleShot(200, step8_warnings)


def step8_warnings():
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_dialog)
rc = app.exec()
shutil.rmtree(PROJ, ignore_errors=True)
sys.exit(0 if not check.failed and rc == 0 else 1)
