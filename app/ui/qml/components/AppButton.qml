import QtQuick
import QtQuick.Controls.Basic
import ".."

Button {
    id: btn
    property string kind: "secondary"   // primary / secondary / danger / ghost
    padding: 8
    leftPadding: 18
    rightPadding: 18
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsBody

    contentItem: Text {
        text: btn.text
        color: !btn.enabled ? Theme.textTertiary
             : btn.kind === "primary" ? "#1D1B17"
             : btn.kind === "danger" ? Theme.danger
             : Theme.textPrimary
        font: btn.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: Theme.rBtn
        color: !btn.enabled ? "transparent"
             : btn.kind === "primary" ? (btn.pressed ? "#C2913F" : btn.hovered ? "#EFC271" : Theme.accent)
             : btn.kind === "danger" ? (btn.pressed ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.22) : btn.hovered ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.12) : "transparent")
             : (btn.pressed ? Theme.bgActive : btn.hovered ? Theme.bgHover : "transparent")
        border.width: btn.kind === "primary" || btn.kind === "ghost" ? 0 : 1
        border.color: btn.kind === "danger"
             ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, btn.hovered ? 0.55 : 0.35)
             : (btn.activeFocus ? Theme.accent : Theme.borderStrong)
        Behavior on color { ColorAnimation { duration: 110 } }
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }
}
