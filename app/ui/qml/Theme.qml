pragma Singleton
import QtQuick

QtObject {
    // ===== 千笔一文 V0.9.9 设计系统（ZCode 实测复刻版）=====
    // 实测 ZCode：基底 #161616 中性灰 · 近乎单色 · 白色主操作
    // 层次 = 表面亮度阶梯 + #2A2A2A 实色发丝线；圆角小（控件4/卡片6）；密度紧凑

    // 背景 · 中性灰阶
    readonly property color bgPage: "#1A1A1A"    // 编辑区（最亮表面）
    readonly property color bgPanel: "#161616"   // 图标栏/侧栏面板
    readonly property color bgCard: "#1F1F1F"    // 卡片/输入
    readonly property color bgHover: "#262626"   // 悬停
    readonly property color bgActive: "#2D2D2D"  // 按下/激活
    readonly property color bgLog: "#111111"     // 日志（最深）

    // 文字
    readonly property color textPrimary: "#F2F1F0"
    readonly property color textSecondary: "#9D9D9D"
    readonly property color textTertiary: "#7E7E7E"

    // 强调与状态（克制用色：主操作=白，状态色只出现在徽章/指示点）
    readonly property color accent: "#4E9CFF"    // 蓝 · 进行中/链接（少量）
    readonly property color success: "#3FB68B"
    readonly property color danger: "#E5534B"
    readonly property color info: "#8AB4E8"
    readonly property color muted: "#7E7E7E"

    // 边框 · 实色发丝线（ZCode 用实色，不用透明度描边）
    readonly property color border: "#2A2A2A"
    readonly property color borderStrong: "#3D3D3D"

    // 卡片顶部高光：已废弃（兼容旧引用）
    readonly property color cardHighlight: "transparent"

    // 字体：UI 全无衬线；衬线只用于「读」的场景
    readonly property string uiFont: "Microsoft YaHei UI"
    readonly property string serifFont: "Source Han Serif SC"
    readonly property string monoFont: "JetBrains Mono"

    // 字号（紧凑层级）
    readonly property int fsTiny: 11
    readonly property int fsSmall: 12
    readonly property int fsBody: 13
    readonly property int fsTitle: 14
    readonly property int fsBig: 20

    // 圆角（ZCode 级：小而克制）
    readonly property int rCard: 6
    readonly property int rBtn: 4
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
