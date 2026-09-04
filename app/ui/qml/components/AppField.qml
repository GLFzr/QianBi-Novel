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
            Behavior on border.color { ColorAnimation { duration: 120 } }
        }
    }
}
