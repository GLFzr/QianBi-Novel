import QtQuick
import QtQuick.Controls.Basic
import ".."

SpinBox {
    id: spin
    property string overrideText: ""     // 非空时替代默认数值显示（如 temperature ÷10）

    palette.text: Theme.textPrimary
    palette.buttonText: Theme.textPrimary

    contentItem: TextInput {
        text: spin.overrideText !== "" ? spin.overrideText : spin.displayText
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsBody
        horizontalAlignment: Qt.AlignHCenter
        verticalAlignment: Qt.AlignVCenter
        readOnly: !spin.editable
        validator: spin.validator
        selectionColor: Theme.accent
        selectedTextColor: Theme.selectedText
    }

    background: Rectangle {
        radius: Theme.rBtn
        color: Theme.bgHover
        border.width: 1
        border.color: spin.activeFocus ? Theme.accent : Theme.border
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            Rectangle {
                // U-09 收口：焦点环真接线（Theme.focusRing/focusRingWidth 首批消费者）
                anchors.fill: parent
                anchors.margins: -3
                radius: parent.radius + 3
                color: "transparent"
                border.color: Theme.focusRing
                border.width: Theme.focusRingWidth
                visible: spin.activeFocus
            }
    }

    up.indicator: Rectangle {
        x: spin.mirrored ? 0 : parent.width - width
        width: 30
        height: parent.height
        radius: Theme.rBtn
        color: spin.up.pressed ? Theme.bgCard : "transparent"
        AppIcon {
            anchors.centerIn: parent
            name: "plus"
            size: 12
            color: Theme.textSecondary
        }
    }

    down.indicator: Rectangle {
        x: spin.mirrored ? parent.width - width : 0
        width: 30
        height: parent.height
        radius: Theme.rBtn
        color: spin.down.pressed ? Theme.bgCard : "transparent"
        AppIcon {
            anchors.centerIn: parent
            name: "minus"
            size: 12
            color: Theme.textSecondary
        }
    }
}
