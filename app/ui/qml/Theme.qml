pragma Singleton
import QtQuick

// ===== 千笔一文 v0.17.0 设计系统（3 主题可切换）=====
// 3 套配色：夜间（默认）/ 羊皮纸（亮色暖色）/ 纯白（亮色冷色）
// 切换通过 bridge.setTheme(name) → cfg.ui_theme → themeChanged 信号
// QML 端使用 Theme.xxx 自动取当前主题的色值
//
// 设计基准（v0.17 成熟化）：
// 1. 明度阶梯造深度：bgPanel < bgPage < bgCard，相邻层明度差 ≥8/255；
//    bgLog 最深（内嵌日志/控制台），bgHover/bgActive 是 bgCard 的交互衍生
// 2. 一切卡片必带 1px hairline（border）；弹窗用 borderStrong + overlay 遮罩
// 3. 强调色只小面积使用（主按钮/激活态/焦点环/细进度条）；语义色用于点/条/徽章
// 4. 字号 6 档、圆角 4 档、间距 6 档，全部走 token，禁止字面量散落

QtObject {
    id: root

    // ---- 主题色表（3 套）----
    readonly property var _themes: ({
        "qianbi_night": {
            // 背景 · 微冷灰阶（相邻层明度差 ≥8）
            bgPage: "#1D2025",      // 编辑区/主内容面
            bgPanel: "#15171B",     // 图标栏/侧栏面板（最深大面积）
            bgCard: "#252930",      // 卡片/输入（明显浮起）
            bgHover: "#2D323A",     // 悬停
            bgActive: "#363C46",    // 按下/激活
            bgLog: "#101215",       // 日志/终端（最深）
            // 文字
            textPrimary: "#F2F1F0",
            textSecondary: "#A6ACB8",
            textTertiary: "#8A919D",
            // 强调
            accent: "#4E9CFF",
            accentHover: "#6CACFF",
            accentPressed: "#3D7FD9",
            accentText: "#FFFFFF",
            selectedText: "#10131A",
            success: "#43A57E",
            warn: "#D9A03F",
            danger: "#D8574F",
            info: "#8AB4E8",
            muted: "#8A919D",
            // 边框
            border: "#30353E",
            borderStrong: "#454C58",
            // 弹窗遮罩（全屏变暗，Apple modal）
            overlay: "#73000000",
            // 三色高亮（阅读器用）
            highlightYellow: "#FFD86E",
            highlightGreen: "#5FE39A",
            highlightRed: "#FF6E6E",
            // 中性色阶（U-01）：n50 最亮 → n900 最深，夜间主题取灰蓝系
            n50: "#F2F4F8", n100: "#D5DAE2", n200: "#B4BCC8", n300: "#8D97A6",
            n400: "#6B7686", n500: "#4C5666", n600: "#3A4250", n700: "#2D3440",
            n800: "#232932", n900: "#171A20",
            // 浮起面（U-01）：比 bgCard 再高一层的 surface（弹窗/浮动工具栏）
            bgRaise: "#2B3039",
            // 阴影色（U-01）：手绘多层 Rectangle 柔影用（§5.4 红线①：不上 MultiEffect）
            shadowColor: "#000000",
        },
        "qianbi_parchment": {
            // 羊皮纸：暖色亮底
            bgPage: "#FAF3E1",
            bgPanel: "#F0E5CC",
            bgCard: "#FFFBEE",
            bgHover: "#EEE2C6",
            bgActive: "#E3D2A6",
            bgLog: "#EDE1C0",
            textPrimary: "#40362A",
            textSecondary: "#75664C",
            textTertiary: "#93866C",
            accent: "#185FA5",
            accentHover: "#2A72B8",
            accentPressed: "#124C86",
            accentText: "#FFFFFF",
            selectedText: "#FFFFFF",
            success: "#2E7D5B",
            warn: "#A8791F",
            danger: "#B23A2A",
            info: "#4A7C8A",
            muted: "#93866C",
            border: "#D9C9A6",
            borderStrong: "#BCA476",
            overlay: "#52403A3A",
            highlightYellow: "#E8B43A",
            highlightGreen: "#5FA86B",
            highlightRed: "#C25A4A",
            // 中性色阶（U-01）：羊皮纸暖棕系
            n50: "#FBF6E8", n100: "#EFE3C6", n200: "#DFCEA8", n300: "#C9B488",
            n400: "#AE9670", n500: "#8F7A58", n600: "#6E5D42", n700: "#524634",
            n800: "#3B3226", n900: "#2A241B",
            bgRaise: "#FFFDF2",
            shadowColor: "#52403A",
        },
        "qianbi_plain": {
            // 纯白：冷色亮底
            bgPage: "#FFFFFF",
            bgPanel: "#F2F4F7",
            bgCard: "#FFFFFF",
            bgHover: "#E9EDF2",
            bgActive: "#DCE2EA",
            bgLog: "#F8FAFC",
            textPrimary: "#191C20",
            textSecondary: "#4E565F",
            textTertiary: "#6E7680",
            accent: "#2F7CD6",
            accentHover: "#4390E5",
            accentPressed: "#2668B5",
            accentText: "#FFFFFF",
            selectedText: "#FFFFFF",
            success: "#2F9067",
            warn: "#B07A1E",
            danger: "#D5443B",
            info: "#4A7FA6",
            muted: "#6E7680",
            border: "#E2E6EB",
            borderStrong: "#C6CDD5",
            overlay: "#52202933",
            highlightYellow: "#E8C24A",
            highlightGreen: "#4FA86B",
            highlightRed: "#D44A4A",
        }
    })

    // 当前主题名（由 C++ 端 cfg.ui_theme 决定，QML 端用 _pick() 取色）
    // QML 没法直接访问 Bridge 单例；用 _active 缓存 + themeChanged 信号触发重读
    property string _active: "qianbi_night"
    function _pick(name) {
        return _themes[_active] && _themes[_active][name] !== undefined
                ? _themes[_active][name] : _themes["qianbi_night"][name]
    }
    function setActive(name) {
        if (_themes[name]) _active = name
    }

    // ===== 背景 =====
    readonly property color bgPage: _pick("bgPage")
    readonly property color bgPanel: _pick("bgPanel")
    readonly property color bgCard: _pick("bgCard")
    readonly property color bgHover: _pick("bgHover")
    readonly property color bgActive: _pick("bgActive")
    readonly property color bgLog: _pick("bgLog")

    // ===== 文字 =====
    readonly property color textPrimary: _pick("textPrimary")
    readonly property color textSecondary: _pick("textSecondary")
    readonly property color textTertiary: _pick("textTertiary")

    // ===== 强调 =====
    readonly property color accent: _pick("accent")
    readonly property color accentHover: _pick("accentHover")
    readonly property color accentPressed: _pick("accentPressed")
    // accentText：强调色上的文字/图标/勾（主按钮、选中态）
    readonly property color accentText: _pick("accentText")
    // selectedText：选中文本颜色（浅底主题用白，深底主题用深）
    readonly property color selectedText: _pick("selectedText")
    // accentSoft：强调色的淡底（选中态、图标底），随主题取 alpha
    readonly property color accentSoft: _pick("accentSoft") !== undefined ? _pick("accentSoft")
        : Qt.rgba(accent.r, accent.g, accent.b, 0.14)
    readonly property color success: _pick("success")
    readonly property color warn: _pick("warn")
    readonly property color danger: _pick("danger")
    readonly property color info: _pick("info")
    readonly property color muted: _pick("muted")
    // 语义淡底（v1.2 波次1）：替代全库手调 Qt.rgba alpha（15 种离散值收敛到统一令牌）
    readonly property color successSoft: Qt.rgba(success.r, success.g, success.b, 0.14)
    readonly property color warnSoft: Qt.rgba(warn.r, warn.g, warn.b, 0.14)
    readonly property color dangerSoft: Qt.rgba(danger.r, danger.g, danger.b, 0.12)
    readonly property color infoSoft: Qt.rgba(info.r, info.g, info.b, 0.12)

    // ===== 边框与遮罩 =====
    readonly property color border: _pick("border")
    readonly property color borderStrong: _pick("borderStrong")
    readonly property color overlay: _pick("overlay")

    // ===== 阅读器三色高亮 =====
    readonly property color highlightYellow: _pick("highlightYellow")
    readonly property color highlightGreen: _pick("highlightGreen")
    readonly property color highlightRed: _pick("highlightRed")

    // ===== 字体 =====
    // MiSans 由 main.py 启动时经 QFontDatabase 注册（assets/fonts，四字重一个家族，
    // font.weight 直接可用）；未注册（理论上仅开发环境异常）时回落系统雅黑。
    readonly property string uiFont: "MiSans"
    readonly property string uiFontFallback: "Microsoft YaHei UI"
    // U-06：衬线/等宽不随包（控制体积），改为全 Windows 保证存在的家族回落链
    // ——干净机器上不再静默消失（思源宋体/JetBrains Mono 仅开发者机器有）
    readonly property string serifFont: "SimSun, NSimSun, serif"
    readonly property string monoFont: "Consolas, Courier New, monospace"
    // 动效令牌（v1.2 波次1 地基：全库 Behavior/Animation 时长一律引用这里，禁止字面量）
    readonly property int durFast: 120    // hover/press/focus/色值微反馈
    readonly property int durNormal: 200  // 面板切换、抽屉、门条、日志渐入
    readonly property int durSlow: 320    // 弹窗出入场、全屏过渡
    readonly property int durLoop: 1400   // 呼吸/循环单周期（克制的节奏）
    readonly property int durIndet: 1600  // 不确定态扫过周期
    readonly property var easeOut: Easing.OutCubic   // 入场/推进（减速收尾）
    readonly property var easeStd: Easing.InOutQuad  // 双向状态/呼吸
    // 减少动态总闸（v1.2）：循环类动画 running 一律挂 && Theme.motionOK；色值过渡保留
    property bool motionOK: true

    // ===== 字号（6 档）=====
    readonly property int fsMicro: 10   // 徽章/角标（仅限全大写或数字场景）
    readonly property int fsTiny: 11    // 说明/辅助
    readonly property int fsSmall: 12   // 次要正文/列表
    readonly property int fsBody: 13    // 正文/控件
    readonly property int fsTitle: 15   // 面板标题/弹窗标题
    readonly property int fsBig: 20     // 页面大标题/统计数字

    // ===== 圆角（4 档 + 胶囊）=====
    readonly property int rSm: 4        // 小控件：输入框、按钮
    readonly property int rMd: 8        // 中块：行卡、瓦片
    readonly property int rLg: 12       // 大卡/弹窗内层
    readonly property int rCard: 8      // 标准卡片
    readonly property int rBtn: 5       // 按钮
    readonly property int rBadge: 99    // 胶囊

    // ===== 间距（6 档节奏）=====
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24

    // ===== 浮起与阴影（U-01：令牌先于质感——U-08 卡片分级/弹窗阴影的领取处）=====
    readonly property color bgRaise: _pick("bgRaise")
    readonly property color n50: _pick("n50")
    readonly property color n100: _pick("n100")
    readonly property color n200: _pick("n200")
    readonly property color n300: _pick("n300")
    readonly property color n400: _pick("n400")
    readonly property color n500: _pick("n500")
    readonly property color n600: _pick("n600")
    readonly property color n700: _pick("n700")
    readonly property color n800: _pick("n800")
    readonly property color n900: _pick("n900")
    readonly property color shadowColor: _pick("shadowColor")
    // 阴影 3 档：e1 悬浮卡 / e2 弹出层 / e3 模态弹窗（多层 Rectangle 手绘，颜色×透明度）
    readonly property real shE1Alpha: 0.10
    readonly property real shE2Alpha: 0.16
    readonly property real shE3Alpha: 0.24
    // 焦点环：聚焦控件外环统一（AppField/AppSelect/AppSpinBox U-09 领取）
    readonly property int focusRingWidth: 2
    readonly property color focusRing: Qt.rgba(accent.r, accent.g, accent.b, 0.40)

    // ===== 工具函数 =====
    function stateColor(s) {
        switch (s) {
        case "pass": return success
        case "writing": return accent
        case "needs_fix": return danger
        case "stale": return highlightYellow
        case "outline_ready": return info
        case "untracked": return info
        default: return muted
        }
    }

    function stateLabel(s) {
        switch (s) {
        case "pass": return "通过"
        case "writing": return "写作中"
        case "needs_fix": return "待修"
        case "stale": return "过期"
        case "outline_ready": return "排队"
        case "untracked": return "待补"
        default: return "排队"
        }
    }

    function levelColor(level) {
        switch (level) {
        case "ok": return success
        case "warn": return warn
        case "error": return danger
        default: return textSecondary
        }
    }
}
