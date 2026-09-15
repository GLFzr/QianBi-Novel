import QtQuick
import QtQuick.Controls.Basic
import ".."

Column {
    id: field
    property string label: ""
    property alias text: input.text
    property alias placeholder: input.placeholderText
    property alias echoMode: input.echoMode
    signal editingFinished()          // 转发内部时机：回车 *或* 失焦都算提交，只挂回车会让设置看着没生效
    spacing: 6

    Text {
        visible: field.label !== ""
        text: field.label
        color: Theme.textTertiary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTiny
    }
    TextField {
        id: input
        onEditingFinished: field.editingFinished()
        width: field.width
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsBody
        leftPadding: 10
        rightPadding: 10
        topPadding: 7
        bottomPadding: 7
        placeholderTextColor: Theme.textTertiary
        selectionColor: Theme.accent
        selectedTextColor: Theme.selectedText
        background: Rectangle {
            radius: Theme.rBtn
            color: Theme.bgHover
            border.width: 1
            border.color: input.activeFocus ? Theme.accent : Theme.border
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            Rectangle {
                // U-09 收口：焦点环真接线（Theme.focusRing/focusRingWidth 首批消费者）
                anchors.fill: parent
                anchors.margins: -3
                radius: parent.radius + 3
                color: "transparent"
                border.color: Theme.focusRing
                border.width: Theme.focusRingWidth
                visible: input.activeFocus
            }
        }
    }
}
