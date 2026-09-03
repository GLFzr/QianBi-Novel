# -*- coding: utf-8 -*-
"""发布素材截图：为 README / Release Notes 生成真实界面图。

与 tests/shot_ui.py 的区别：那个跑在 offscreen 软件后端上，字体库是空的
（QFontDatabase.families() == 0），中文全部渲染成豆腐块，只能用于布局走查。
这里必须用 windows 平台插件才有真字体，故单独一支。

用法：python tests/shot_release.py [宽x高]      默认 1500x950
产物：docs/shot_*.png
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_shotrel_home_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QElapsedTimer, QTimer, QUrl
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv[:1])
if not __import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.families():
    print("FATAL: 字体库为空，请确认 QT_QPA_PLATFORM=windows（offscreen 无字体）")
    sys.exit(2)

_SIZE = sys.argv[1] if len(sys.argv) > 1 else "1500x950"
W, H = (int(x) for x in _SIZE.lower().split("x"))
# 两段式取景：默认拍自动档各面板；传 cw 只拍共写档对话界面。
# 共写档必须在建引擎前置位（见下方注释），无法与自动档共用一次进程。
CW_PASS = len(sys.argv) > 2 and sys.argv[2].lower() == "cw"

from app import project
from app.core import memory, state as st

# ---- 演示书：内容全部为本次生成的假数据，不含任何真实作品 ----
TMP = tempfile.mkdtemp(prefix="qbn_shotrel_proj_")
PROJ = project.create_project(TMP, "示例·守灯人")
project.write_idea_info(PROJ, "修仙·凡人流", "番茄", "主角每救一人，自己的寿元便少一年", 300)

project.write_file(
    os.path.join(PROJ, "设定", "题材定位.md"),
    "# 题材定位\n\n"
    "## 读者契约\n凡人流视角，代价先行：每一次变强都要写明失去了什么。\n\n"
    "## 主要角色表\n"
    "| 角色 | 定位 | 声口 |\n|---|---|---|\n"
    "| 沈拾 | 主角·守灯人 | 短句，不解释 |\n"
    "| 阿栾 | 女主·药童 | 爱反问 |\n"
    "| 老执灯 | 师父·已故 | 只出现在遗言里 |\n",
)
project.write_file(
    os.path.join(PROJ, "大纲", "大纲.md"),
    "# 全书大纲\n\n## 第1章-第60章 第一卷·灯下黑\n"
    "- 主线：沈拾接掌残灯，发现守灯人的寿元账本\n- 终局钩子：灯油即人命\n\n"
    "## 第61章-第140章 第二卷·换骨\n- 主线：以寿元换修为的第一次失手\n",
)
project.write_file(
    os.path.join(PROJ, "设定", "世界书.md"),
    "## 世界书\n\n### 资源规则\n"
    "- 寿元：唯一硬通货，不可转让、不可借贷\n"
    "- 灯油：守灯人专属，燃一盏折一年\n\n"
    "### 势力\n- 守灯司：管理残灯与寿元账目\n- 换骨楼：地下销赃寿元的中介\n\n"
    "### 角色\n- 沈拾：守灯人，现存寿元四十一年\n",
)
project.write_file(
    os.path.join(PROJ, "设定", "正则.md"),
    "- 规则：寿元消耗必须写明具体年数｜level：must｜scope：全书\n"
    "- 规则：不得出现凭空变强的桥段｜level：must｜scope：全书\n"
    "- 规则：老执灯已故，不得以活人身份出场｜level：must｜scope：全书\n",
)

_TITLES = {1: "灯下黑", 2: "第一笔账", 3: "换骨楼"}
_BODY = (
    "残灯只剩一线芯，沈拾把袖子挽到肘上，去够那盏挂在梁上的旧灯。\n\n"
    "指尖刚碰到灯罩，识海里那本账就翻开了。第一页写着他的名字，名字底下一行小字："
    "现存寿元，四十一年。他数了数，比三年前少了两格，格子里填的不是数字，是三张人脸。\n\n"
    "\"你又去点灯了。\"阿栾站在门口，手里端着药，\"这回折了几年？\"\n\n"
    "\"不多。\"\n\n"
    "\"不多是几年？\"\n\n"
    "沈拾没答。他把灯芯拨正，火苗跳起来，照见梁上那一排空灯座——七个，全空着。"
    "老执灯在世时说过，一盏灯一条命，座子空了就说明人没了。他数过很多回，"
    "每回数完，自己的寿元就好像又薄了一层。\n\n"
    "\"药凉了。\"他说。\n\n"
    "阿栾把碗搁在门槛上，没进来。她进来就要看见那本账，看见了就要算，"
    "算出来她就不肯再给他熬药了。这是他们之间心照不宣的事，"
    "像一盏不敢点太亮的灯，够用就行。\n\n"
    "外头有人敲梆子，三更了。沈拾把最后一个空灯座擦干净，动作很轻，"
    "像怕吵醒谁。擦到第三遍，他忽然停住——座子底下刻着两个小字，"
    "是他自己的名字。\n"
)
for n, t in _TITLES.items():
    project.write_file(
        project.get_chapter_path(PROJ, n, t),
        f"# 第{n}章 {t}\n\n" + _BODY,
    )
for n in (4, 5, 6):
    project.write_file(
        project.get_outline_path(PROJ, n),
        f"===第{n}章===\n### 第 {n} 章：{'账本' if n == 4 else '来客' if n == 5 else '失手'}\n"
        f"- 核心事件：沈拾核对寿元账目，发现第三张人脸\n"
        f"- 出场顺序：沈拾、阿栾\n"
        f"- 字数目标：3000\n"
        f"- 章末钩子：灯座上的名字自己变深了一格\n",
    )

s = st.load_state(PROJ)
s["total_chapters"] = 300
s["stage"] = st.STAGE_PROSE
for n, t, w, status in ((1, "灯下黑", 3024, "pass"), (2, "第一笔账", 2981, "pass"),
                        (3, "换骨楼", 2866, "needs_fix")):
    st.append_history(PROJ, s, {"num": n, "title": t, "words": w,
                                "deslop_blocking": 0 if status == "pass" else 2,
                                "deslop_advisory": 2, "status": status})
st.save_state(PROJ, s)
memory.write_global_summary(PROJ, "沈拾接掌残灯，发现自己名字被刻在空灯座下——寿元账本早已记下了他。")
memory.apply_foreshadow_diff(PROJ, 3, [("空灯座刻名", "卷一末", "第 30 章")], [])

from app import config as cfg_mod

_cfg = cfg_mod.load_config()
_cfg.setdefault("general", {})["onboarded"] = True
cfg_mod.save_config(_cfg)

from app.ui.bridge import Bridge

bridge = Bridge()
bridge.openProject(PROJ)
bridge.openChapter(3)

# 共写档必须在 QML 装载之前就位：CwDialogueDock 的 visible 绑定只在创建时求值一次，
# 引擎起来后再从 Python 翻 cwMode 不会重算，dock 会一直藏着。
if CW_PASS:
    from app.core import co_dialogue

    cs = st.load_state(PROJ)
    cw = st.ensure_cw(cs)
    cw["stage"] = st.STAGE_CW_PROSE
    for role, txt in (
        ("user", "第 3 章我想让沈拾第一次失手——他救不下那个人，寿元照样折了。"),
        ("agent", "同意，这一章正好把「代价先行」的读者契约坐实：救人不保证不折寿。"
                  "建议折损写成具体数——账页上从四十一年跳到三十八年，读者能替他心疼。"),
        ("user", "对，别写「仿佛失去了什么」这种虚的。"),
        ("agent", "已记入正则：寿元消耗必须写明具体年数（must／全书）。"
                  "另提示：老执灯已故，本章若让他以活人身份出场，审校会判阻塞。"),
    ):
        co_dialogue.transcript_append(cs, st.STAGE_CW_PROSE, role, txt)
    st.save_state(PROJ, cs)
    bridge.setCwMode(True)
    # migrate_mode 会把阶段复位到 cw_unit，这里再钉回正文写作
    cs = st.load_state(PROJ)
    st.ensure_cw(cs)["stage"] = st.STAGE_CW_PROSE
    st.save_state(PROJ, cs)
    bridge.selectCwStage(st.STAGE_CW_PROSE)

from PySide6.QtQml import QQmlApplicationEngine

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", bridge)
QML = os.path.join(os.getcwd(), "app", "ui", "qml")
engine.addImportPath(QML)
engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
assert engine.rootObjects(), "QML 装载失败"
win = engine.rootObjects()[0]
win.resize(W, H)
try:
    win.setWidth(W)
    win.setHeight(H)
except Exception:
    pass

OUT = os.path.join(os.getcwd(), "docs")
os.makedirs(OUT, exist_ok=True)


def settle(ms=600):
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        app.processEvents()


def shoot(name):
    # 根对象在 Python 侧只是裸 QWindow，没有 grabWindow()；
    # windows 平台上用屏幕抓取真实窗口像素。
    # 显示器关着时窗口不会自己重绘，抓到的永远是上一帧——必须显隐一次强制合成
    # （同 tests/ui_audit.py 的做法）。
    win.setVisible(False)
    win.setVisible(True)
    settle(400)
    img = app.primaryScreen().grabWindow(win.winId()).toImage()
    path = os.path.join(OUT, f"shot_{name}.png")
    img.save(path)
    print(f"SHOT {name:10s} {img.width()}x{img.height()} -> {os.path.relpath(path, os.getcwd())}")


win.show()


def show_panel(key: str):
    win.setProperty("activePanel", key)


def run():
    if CW_PASS:
        show_panel("pipeline")
        settle(1200)
        print("cwMode =", bridge.cwMode, "| stage =", bridge.cwStageKey)
        shoot("co_writing")
    else:
        for label in ("shelf", "pipeline", "chapters", "library", "settings"):
            show_panel(label)
            settle(1000)
            # 强制显隐会让 ComboBox 弹层残留成一块白框，按 Esc 收掉
            from PySide6.QtCore import QEvent, Qt
            from PySide6.QtGui import QKeyEvent
            for etype in (QEvent.KeyPress, QEvent.KeyRelease):
                app.sendEvent(win, QKeyEvent(etype, 0x1000000, Qt.KeyboardModifier.NoModifier))
            settle(300)
            shoot(label)
    print("SHOTS_DONE")
    app.quit()


QTimer.singleShot(1200, run)
app.exec()
