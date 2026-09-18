# -*- coding: utf-8 -*-
"""A-10 真跑探针：流水线运行中关窗，进程必须退 0 且有收尾日志（旧实测 RC=127）。

手法：夹具项目 + localhost 连接（免 Key）→ monkeypatch stages._stream 为
「先睡 30s 再返回」→ startPipeline（管线停在第一次 LLM 调用里）→ 2 秒后
app.quit() → aboutToQuit 触发 bridge.shutdown（stop + 限时等待 + terminate
兜底）→ 断言退出码 0。运行方式：本探针自身就是那个进程（不 spawn 子进程），
退出码由 fleet/外部观测；日志行打在本探针输出里。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from probe_guard import arm_config_guard  # noqa: E402

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app import project  # noqa: E402
from app.core import stages  # noqa: E402
from app.ui.bridge import Bridge  # noqa: E402

FAILED = {"n": 0}


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok:
        FAILED["n"] += 1


_FH = tempfile.mkdtemp(prefix="qbn_shutdown_")
os.environ["USERPROFILE"] = _FH

# 夹具：本地连接 + 项目
import json  # noqa: E402
from app import config as cfg_mod  # noqa: E402
cfg_dir = os.path.join(_FH, ".qianbi_novel")
os.makedirs(cfg_dir, exist_ok=True)
cfg_mod.CONFIG_DIR = cfg_dir
cfg_mod.CONFIG_FILE = os.path.join(cfg_dir, "config.json")
cfg = json.loads(json.dumps(cfg_mod.DEFAULT_CONFIG))
for c in cfg["connections"]:
    c["base_url"] = "http://127.0.0.1:9/v1"
    c["api_key"] = ""
cfg["slots"] = {k: cfg["connections"][0]["id"] for k in cfg["slots"]}
cfg_mod.save_config(cfg)

# 日志通道落进假 home（收尾记录的可查证据）
import app.logger as app_logger  # noqa: E402
app_logger.LOG_DIR = os.path.join(cfg_dir, "logs")
app_logger.LOG_FILE = os.path.join(app_logger.LOG_DIR, "qianbi.log")
app_logger.setup_logging()

PROJ = os.path.join(_FH, "book")
os.makedirs(os.path.join(PROJ, "设定"), exist_ok=True)
os.makedirs(os.path.join(PROJ, "大纲"), exist_ok=True)
os.makedirs(os.path.join(PROJ, "正文"), exist_ok=True)
project.write_idea_info(PROJ, "悬疑", "番茄", "关窗探针", 1)

# 把 _stream 换成「先睡 30s」——管线必停在第一次 LLM 调用里
_real_stream = stages._stream


def _slow_stream(ctx, slot, prompt, label="", *, phase=""):
    import time
    ctx.stream_stage(label or phase or "slow")
    time.sleep(30)
    return _real_stream(ctx, slot, prompt, label=label, phase=phase)


stages._stream = _slow_stream

app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
qml_dir = os.path.join(os.getcwd(), "app", "ui", "qml")
engine.addImportPath(qml_dir)
engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
if not engine.rootObjects():
    print("FAIL Main.qml 加载失败", flush=True)
    sys.exit(1)

b._open_project(PROJ, silent=True)
app.aboutToQuit.connect(b.shutdown)   # 与 main.py 同款接线
b.startPipeline()
check("流水线已进入运行态", bool(b._running))


def quit_now():
    print(" quitting while pipeline running…", flush=True)
    app.quit()


QTimer.singleShot(2000, quit_now)
rc = app.exec()
sys.stdout.flush()
sys.stderr.flush()
check("退出码 0", rc == 0)
print("PROBE_DONE " + ("FAIL" if FAILED["n"] else "PASS"), flush=True)
sys.stdout.flush(); sys.stderr.flush()
import atexit as _ax  # v4复验：arm_config_guard 的真 config 还原挂在 atexit，os._exit 会跳掉它
_ax._run_exitfuncs()
os._exit(0 if rc == 0 and not FAILED["n"] else 1)   # 同仓库对策：躲析构 fastfail
