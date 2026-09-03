pragma Singleton
import QtQuick

// ===== 千笔一文 v0.13.0 设计系统（3 主题可切换）=====
// 3 套配色：夜间（默认）/ 羊皮纸（亮色暖色）/ 纯白（亮色冷色）
// 切换通过 bridge.setTheme(name) → cfg.ui_theme → themeChanged 信号
// QML 端使用 Theme.xxx 自动取当前主题的色值

QtObject {
    id: root

    // ---- 主题色表（3 套）----
    readonly property var _themes: ({
        "qianbi_night": {
            // 背景 · 中性灰阶
            bgPage: "#1A1A1A",      // 编辑区（最亮表面）
            bgPanel: "#161616",     // 图标栏/侧栏面板
            bgCard: "#1F1F1F",      // 卡片/输入
            bgHover: "#262626",     // 悬停
            bgActive: "#2D2D2D",    // 按下/激活
            bgLog: "#111111",       // 日志（最深）
            // 文字
            textPrimary: "#F2F1F0",
            textSecondary: "#9D9D9D",
            textTertiary: "#7E7E7E",
            // 强调
            accent: "#4E9CFF",
            success: "#3FB68B",
            danger: "#E5534B",
            info: "#8AB4E8",
            muted: "#7E7E7E",
            // 边框
            border: "#2A2A2A",
            borderStrong: "#3D3D3D",
            // 三色高亮（阅读器用）
            highlightYellow: "#FFD86E",
            highlightGreen: "#5FE39A",
            highlightRed: "#FF6E6E",
        },
        "qianbi_parchment": {
            // 羊皮纸：暖色亮底
            bgPage: "#FBF5E6",
            bgPanel: "#F4EAD6",
            bgCard: "#FFFCF0",
            bgHover: "#EFE3C7",
            bgActive: "#E5D5A8",
            bgLog: "#E8DCBA",
            textPrimary: "#43392A",
            textSecondary: "#7A6A4E",
            textTertiary: "#A89A7A",
            accent: "#185FA5",
            success: "#2E7D5B",
            danger: "#B23A2A",
            info: "#4A7C8A",
            muted: "#A89A7A",
            border: "#D4C29B",
            borderStrong: "#B89F70",
            highlightYellow: "#E8B43A",
            highlightGreen: "#5FA86B",
            highlightRed: "#C25A4A",
        },
        "qianbi_plain": {
            // 纯白：冷色亮底
            bgPage: "#FFFFFF",
            bgPanel: "#F5F5F5",
            bgCard: "#FFFFFF",
            bgHover: "#EFEFEF",
            bgActive: "#E5E5E5",
            bgLog: "#FAFAFA",
            textPrimary: "#1A1A1A",
            textSecondary: "#5A5A5A",
            textTertiary: "#8A8A8A",
            accent: "#378ADD",
            success: "#3FB68B",
            danger: "#DC4A40",
            info: "#5A8FB8",
            muted: "#8A8A8A",
            border: "#E0E0E0",
            borderStrong: "#C0C0C0",
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
    readonly property color success: _pick("success")
    readonly property color danger: _pick("danger")
    readonly property color info: _pick("info")
    readonly property color muted: _pick("muted")

    // ===== 边框 =====
    readonly property color border: _pick("border")
    readonly property color borderStrong: _pick("borderStrong")
    readonly property color cardHighlight: "transparent"

    // ===== 阅读器三色高亮 =====
    readonly property color highlightYellow: _pick("highlightYellow")
    readonly property color highlightGreen: _pick("highlightGreen")
    readonly property color highlightRed: _pick("highlightRed")

    // ===== 字体 =====
    readonly property string uiFont: "Microsoft YaHei UI"
    readonly property string serifFont: "Source Han Serif SC"
    readonly property string monoFont: "JetBrains Mono"

    // ===== 字号 =====
    readonly property int fsTiny: 11
    readonly property int fsSmall: 12
    readonly property int fsBody: 13
    readonly property int fsTitle: 14
    readonly property int fsBig: 20

    // ===== 圆角 =====
    readonly property int rCard: 6
    readonly property int rBtn: 4
    readonly property int rBadge: 99

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
        case "warn": return accent
        case "error": return danger
        default: return textSecondary
        }
    }
}
