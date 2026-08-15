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
             : btn.kind === "primary" ? (btn.pressed ? "#C99B4A" : btn.hovered ? "#EFC271" : Theme.accent)
             : (btn.hovered ? Theme.bgHover : "transparent")
        border.width: btn.kind === "primary" || btn.kind === "ghost" ? 0 : 1
        border.color: btn.kind === "danger" ? "#73D9755C" : Theme.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
