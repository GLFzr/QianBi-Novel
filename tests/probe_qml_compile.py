# -*- coding: utf-8 -*-
"""QML 静态装配探针：逐个编译 app/ui/qml 下的每个 .qml

为什么要单独一个探针：QML 里的类型/属性写错（比如给 Text 赋 selectByMouse），
后果是整个 Main.qml 加载失败，而 QQmlApplicationEngine 加载失败时**什么都不打印**，
只留一句 rootObjects() 为空的断言。真机跑起来才知道，探针里查半天查不到。
这里把每个文件单独编译一遍，错误直接列出来。

用法：python tests/probe_qml_compile.py [目录或文件...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from probe_guard import arm_config_guard      # noqa: E402
arm_config_guard()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl, qInstallMessageHandler      # noqa: E402
from PySide6.QtGui import QGuiApplication     # noqa: E402
from PySide6.QtQml import QQmlEngine, QQmlComponent  # noqa: E402

WARN = []


def _cap(mode, ctx, msg):
    WARN.append("%s: %s" % (getattr(ctx, "file", "?"), msg))


qInstallMessageHandler(_cap)


def _sources(argv):
    if argv:
        out = []
        for a in argv:
            p = a if os.path.isabs(a) else os.path.join(ROOT, a)
            if os.path.isdir(p):
                for dirpath, _dirs, files in os.walk(p):
                    out += [os.path.join(dirpath, f) for f in files if f.endswith(".qml")]
            else:
                out.append(p)
        return sorted(out)
    base = os.path.join(ROOT, "app", "ui", "qml")
    return sorted(os.path.join(d, f) for d, _s, fs in os.walk(base)
                  for f in fs if f.endswith(".qml"))


def main() -> int:
    targets = _sources(sys.argv[1:])
    app = QGuiApplication(sys.argv[:1])
    eng = QQmlEngine()
    eng.addImportPath(os.path.join(ROOT, "app", "ui", "qml"))
    from app.ui.bridge import Bridge
    ctx = Bridge()
    eng.rootContext().setContextProperty("bridge", ctx)
    eng.rootContext().setContextProperty("app", app)

    bad = []
    for path in targets:
        comp = QQmlComponent(eng, QUrl.fromLocalFile(path))
        if comp.isReady():
            continue
        errs = [e.toString().split(": ", 1)[-1].strip() for e in comp.errors()]
        # 同一个类型错误会在每个使用它的地方重复报，只留唯一条
        uniq = list(dict.fromkeys(errs))
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        head = "%s：%s" % (rel, uniq[0]) if uniq else "%s：（无错误详情）" % rel
        if len(uniq) > 1:
            head += "（另有 %d 条）" % (len(uniq) - 1)
        bad.append(head)
        for line in uniq[1:3]:
            print("     · %s" % line)
    print("QML 编译 %d 个文件，失败 %d 个" % (len(targets), len(bad)))
    for h in bad:
        print("  FAIL " + h)
    for w in list(dict.fromkeys(WARN))[:5]:
        print("  WARN " + w)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
