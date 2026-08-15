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
        selectedTextColor: "#1D1B17"
    }

    background: Rectangle {
        radius: Theme.rBtn
        color: Theme.bgHover
        border.width: 1
        border.color: spin.activeFocus ? Theme.accent : Theme.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    up.indicator: Rectangle {
        x: spin.mirrored ? 0 : parent.width - width
        width: 30
        height: parent.height
        radius: Theme.rBtn
        color: spin.up.pressed ? Theme.bgCard : "transparent"
        Text {
            anchors.centerIn: parent
            text: "＋"
            color: Theme.textSecondary
            font.pixelSize: Theme.fsSmall
        }
    }

    down.indicator: Rectangle {
        x: spin.mirrored ? parent.width - width : 0
        width: 30
        height: parent.height
        radius: Theme.rBtn
        color: spin.down.pressed ? Theme.bgCard : "transparent"
        Text {
            anchors.centerIn: parent
            text: "－"
            color: Theme.textSecondary
            font.pixelSize: Theme.fsSmall
        }
    }
}
