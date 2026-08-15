pragma Singleton
import QtQuick

QtObject {
    // 背景 · 暖黑四阶
    readonly property color bgPage: "#0F0E0C"
    readonly property color bgPanel: "#161512"
    readonly property color bgCard: "#1D1B17"
    readonly property color bgHover: "#25221C"
    readonly property color bgLog: "#0A0908"

    // 文字
    readonly property color textPrimary: "#EDE9E0"
    readonly property color textSecondary: "#A39E93"
    readonly property color textTertiary: "#6B675E"

    // 强调与状态 · 收敛五色
    readonly property color accent: "#E2B15B"   // 琥珀 · 主行动/进行中
    readonly property color success: "#63C0A8"  // 青玉 · 通过
    readonly property color danger: "#D9755C"   // 赭红 · 待修/阻断
    readonly property color info: "#7FA3C9"     // 雾蓝 · 信息
    readonly property color muted: "#6B675E"    // 烟灰 · 排队/禁用

    // 边框（AARRGGBB）
    readonly property color border: "#12EDE9E0"
    readonly property color borderStrong: "#24EDE9E0"

    // 字体
    readonly property string uiFont: "Microsoft YaHei UI"
    readonly property string serifFont: "Source Han Serif SC"
    readonly property string monoFont: "JetBrains Mono"

    // 字号（桌面应用：正文 14px 为基准）
    readonly property int fsTiny: 12
    readonly property int fsSmall: 13
    readonly property int fsBody: 14
    readonly property int fsTitle: 17
    readonly property int fsBig: 24

    // 圆角
    readonly property int rCard: 12
    readonly property int rBtn: 8
    readonly property int rBadge: 99

    function stateColor(s) {
        switch (s) {
        case "pass": return success
        case "writing": return accent
        case "needs_fix": return danger
        case "outline_ready": return info
        default: return muted
        }
    }

    function stateLabel(s) {
        switch (s) {
        case "pass": return "通过"
        case "writing": return "写作中"
        case "needs_fix": return "待修"
        case "outline_ready": return "排队"
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
