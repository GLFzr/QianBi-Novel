import QtQuick
import QtQuick.Controls.Basic
import ".."

// 通用按钮 · ZCode 风格：平面 + 发丝线 + 快速色彩过渡；可选线性图标
Button {
    id: btn
    property string kind: "secondary"   // primary / secondary / danger / success / ghost
    property string iconName: ""        // AppIcon 名称（空=纯文字）
    property int iconSize: 15
    // 高度下限：内容（13px 文字 + padding）最小需要 ~25px，压到 20/22 会让文字溢出压到描边上
    implicitHeight: 28
    padding: 6
    leftPadding: iconName !== "" ? 10 : 14
    rightPadding: iconName !== "" ? 12 : 14
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsBody

    contentItem: Item {
        // 外层 Item 上报真实内容尺寸，避免「contentItem 带锚点 → 控件放弃按内容定宽」塌缩
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: btn.iconName !== "" ? 6 : 0

            AppIcon {
                visible: btn.iconName !== ""
                name: btn.iconName
                size: btn.iconSize
                color: !btn.enabled ? (btn.kind === "primary" ? Theme.textSecondary : Theme.textTertiary)
                     : btn.kind === "primary" ? Theme.accentText
                     : btn.kind === "danger" ? Theme.danger
                     : btn.kind === "success" ? Theme.success
                     : btn.hovered && btn.kind === "ghost" ? Theme.textPrimary
                     : Theme.textSecondary
            }
            Text {
                text: btn.text
                color: !btn.enabled ? (btn.kind === "primary" ? Theme.textSecondary : Theme.textTertiary)
                     : btn.kind === "primary" ? Theme.accentText
                     : btn.kind === "danger" ? Theme.danger
                     : btn.kind === "success" ? Theme.success
                     : btn.hovered && btn.kind === "ghost" ? Theme.textPrimary
                     : Theme.textSecondary
                font: btn.font
                Behavior on color { ColorAnimation { duration: 110 } }
            }
        }
    }
    background: Rectangle {
        radius: Theme.rBtn
        // 禁用态保留按钮外形：主按钮留灰底，其余留描边——不能退化成裸文字（主次倒挂）
        color: !btn.enabled ? (btn.kind === "primary" ? Theme.bgActive : "transparent")
             : btn.kind === "primary" ? (btn.pressed ? Theme.accentPressed : btn.hovered ? Theme.accentHover : Theme.accent)
             : btn.kind === "danger" ? (btn.pressed ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.22) : btn.hovered ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.12) : "transparent")
             : btn.kind === "success" ? (btn.pressed ? Qt.rgba(Theme.success.r, Theme.success.g, Theme.success.b, 0.22) : btn.hovered ? Qt.rgba(Theme.success.r, Theme.success.g, Theme.success.b, 0.12) : "transparent")
             : (btn.pressed ? Theme.bgActive : btn.hovered ? Theme.bgHover : "transparent")
        border.width: btn.kind === "ghost" ? 0 : 1
        border.color: !btn.enabled ? Theme.border
             : btn.kind === "danger"
             ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, btn.hovered ? 0.55 : 0.35)
             : btn.kind === "success"
             ? Qt.rgba(Theme.success.r, Theme.success.g, Theme.success.b, btn.hovered ? 0.55 : 0.35)
             : (btn.activeFocus ? Theme.accent : Theme.border)
        Behavior on color { ColorAnimation { duration: 110 } }
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }
}
