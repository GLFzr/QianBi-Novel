import QtQuick
import QtQuick.Controls.Basic
import ".."

// 复选框 · 自绘现代样式（方框描边 + 选中填充 + 勾）
CheckBox {
    id: chk
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsSmall
    spacing: 8
    topPadding: 3
    bottomPadding: 3

    indicator: Rectangle {
        implicitWidth: 16
        implicitHeight: 16
        x: chk.leftPadding
        y: chk.height / 2 - height / 2
        radius: 4
        color: chk.checked ? Theme.accent : (chk.hovered ? Theme.bgActive : Theme.bgCard)
        border.width: chk.checked ? 0 : 1
        border.color: chk.hovered ? Theme.borderStrong : Theme.border
        Behavior on color { ColorAnimation { duration: 110 } }

        Canvas {
            anchors.centerIn: parent
            width: 10; height: 10
            visible: chk.checked
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = "#FFFFFF"
                ctx.lineWidth = 1.8
                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                ctx.beginPath()
                ctx.moveTo(1, 5.5)
                ctx.lineTo(4, 8.5)
                ctx.lineTo(9, 1.5)
                ctx.stroke()
            }
        }
    }

    contentItem: Text {
        text: chk.text
        color: chk.enabled ? Theme.textSecondary : Theme.textTertiary
        font: chk.font
        verticalAlignment: Text.AlignVCenter
        leftPadding: chk.indicator.width + chk.spacing
        Behavior on color { ColorAnimation { duration: 110 } }
    }
}
