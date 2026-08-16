pragma Singleton
import QtQuick

QtObject {
    // 背景 · 暖黑五阶（现代深色写作工具：层次分明）
    readonly property color bgPage: "#0F0E0B"
    readonly property color bgPanel: "#171512"
    readonly property color bgCard: "#1F1C17"
    readonly property color bgHover: "#282419"
    readonly property color bgActive: "#2E291C"
    readonly property color bgLog: "#0A0908"

    // 文字
    readonly property color textPrimary: "#EDEAE1"
    readonly property color textSecondary: "#A8A296"
    readonly property color textTertiary: "#6F6A5F"

    // 强调与状态 · 收敛五色
    readonly property color accent: "#E3B35C"   // 琥珀 · 主行动/进行中
    readonly property color success: "#66C4A9"  // 青玉 · 通过
    readonly property color danger: "#DB7861"   // 赭红 · 待修/阻断
    readonly property color info: "#83A5CC"     // 雾蓝 · 信息
    readonly property color muted: "#6F6A5F"    // 烟灰 · 排队/禁用

    // 边框（AARRGGBB）
    readonly property color border: "#14EDEAE1"
    readonly property color borderStrong: "#26EDEAE1"

    // 卡片顶部高光（现代深色 UI 层次感）
    readonly property color cardHighlight: "#12FFFFFF"

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
