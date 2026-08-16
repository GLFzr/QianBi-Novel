import QtQuick
import QtQuick.Controls.Basic
import ".."

// 通用按钮 · ZCode 风格：平面 + 发丝线 + 快速色彩过渡；可选线性图标
Button {
    id: btn
    property string kind: "secondary"   // primary / secondary / danger / ghost
    property string iconName: ""        // AppIcon 名称（空=纯文字）
    property int iconSize: 15
    padding: 6
    leftPadding: iconName !== "" ? 10 : 14
    rightPadding: iconName !== "" ? 12 : 14
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsBody

    contentItem: Row {
        spacing: btn.iconName !== "" ? 6 : 0
        anchors.centerIn: parent

        AppIcon {
            visible: btn.iconName !== ""
            name: btn.iconName
            size: btn.iconSize
            color: !btn.enabled ? Theme.textTertiary
                 : btn.kind === "primary" ? "#161616"
                 : btn.kind === "danger" ? Theme.danger
                 : btn.hovered && btn.kind === "ghost" ? Theme.textPrimary
                 : Theme.textSecondary
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: btn.text
            color: !btn.enabled ? Theme.textTertiary
                 : btn.kind === "primary" ? "#161616"
                 : btn.kind === "danger" ? Theme.danger
                 : btn.hovered && btn.kind === "ghost" ? Theme.textPrimary
                 : Theme.textSecondary
            font: btn.font
            anchors.verticalCenter: parent.verticalCenter
            Behavior on color { ColorAnimation { duration: 110 } }
        }
    }
    background: Rectangle {
        radius: Theme.rBtn
        color: !btn.enabled ? "transparent"
             : btn.kind === "primary" ? (btn.pressed ? "#D9D9D9" : btn.hovered ? "#FFFFFF" : "#F2F1F0")
             : btn.kind === "danger" ? (btn.pressed ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.22) : btn.hovered ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.12) : "transparent")
             : (btn.pressed ? Theme.bgActive : btn.hovered ? Theme.bgHover : "transparent")
        border.width: btn.kind === "primary" || btn.kind === "ghost" ? 0 : 1
        border.color: btn.kind === "danger"
             ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, btn.hovered ? 0.55 : 0.35)
             : (btn.activeFocus ? Theme.accent : Theme.border)
        Behavior on color { ColorAnimation { duration: 110 } }
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }
}
