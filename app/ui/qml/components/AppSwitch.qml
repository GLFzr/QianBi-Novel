import QtQuick
import QtQuick.Controls.Basic
import ".."

// ============================================================
// AppSwitch · 开关（布尔偏好语义）
// 替换「用复选框表达开/关」的原生样式：轨道 + 滑块 + 可选标签。
// 真正的多选/单选语义仍用 AppCheck。
// ============================================================
AbstractButton {
    id: ctl
    property string label: ""
    checkable: true
    spacing: 8
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsSmall

    implicitHeight: 24
    implicitWidth: track.width + spacing + (label !== "" ? textLabel.implicitWidth : 0)

    indicator: Rectangle {
        id: track
        x: 0
        y: ctl.height / 2 - height / 2
        width: 36
        height: 20
        radius: 10
        color: ctl.checked ? Theme.accent : Theme.bgActive
        border.width: 1
        border.color: ctl.checked ? Theme.accent : Theme.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Rectangle {
            id: knob
            x: ctl.checked ? track.width - width - 2 : 2
            y: track.height / 2 - height / 2
            width: 16
            height: 16
            radius: 8
            color: Theme.accentText
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }

    contentItem: Text {
        id: textLabel
        visible: ctl.label !== ""
        text: ctl.label
        color: ctl.enabled ? Theme.textSecondary : Theme.textTertiary
        font: ctl.font
        verticalAlignment: Text.AlignVCenter
        x: track.width + ctl.spacing
        width: implicitWidth
    }
}
