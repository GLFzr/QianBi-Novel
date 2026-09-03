import QtQuick
import QtQuick.Controls.Basic
import ".."

// ============================================================
// AppSelect · 下拉选择（全自绘）
// 替换原生 ComboBox：默认样式带系统箭头/白底弹层，与暗色主题割裂。
// 支持 editable（模型名手动输入场景，内容项为 TextInput 由 ComboBox 接管编辑）。
// ============================================================
ComboBox {
    id: ctl
    implicitHeight: 30
    font.family: Theme.uiFont
    font.pixelSize: Theme.fsBody

    background: Rectangle {
        radius: Theme.rBtn
        color: !ctl.enabled ? Theme.bgHover : ctl.hovered ? Theme.bgHover : Theme.bgCard
        border.width: 1
        border.color: ctl.activeFocus ? Theme.accent : Theme.border
        Behavior on border.color { ColorAnimation { duration: 110 } }
        Behavior on color { ColorAnimation { duration: 110 } }
    }

    contentItem: Item {
        TextInput {
            visible: ctl.editable
            anchors.fill: parent
            leftPadding: 10
            rightPadding: 28
            text: ctl.editText
            color: Theme.textPrimary
            font: ctl.font
            verticalAlignment: TextInput.AlignVCenter
            selectByMouse: true
            selectionColor: Theme.accent
            selectedTextColor: Theme.textPrimary
            clip: true
        }
        Text {
            visible: !ctl.editable
            anchors.fill: parent
            leftPadding: 10
            rightPadding: 28
            text: ctl.displayText
            color: !ctl.enabled ? Theme.textTertiary : Theme.textPrimary
            font: ctl.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    indicator: AppIcon {
        name: "down"
        x: ctl.width - width - 9
        y: ctl.height / 2 - height / 2
        size: 12
        color: ctl.hovered ? Theme.textPrimary : Theme.textSecondary
        Behavior on color { ColorAnimation { duration: 110 } }
    }

    delegate: ItemDelegate {
        id: selDelegate
        width: ctl.width
        height: 30
        highlighted: ctl.highlightedIndex === index
        contentItem: Text {
            leftPadding: 6
            text: ctl.textRole !== "" ? (Array.isArray(ctl.model) ? modelData[ctl.textRole] : model[ctl.textRole])
                                      : modelData
            color: selDelegate.highlighted ? Theme.textPrimary : Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: Theme.rSm
            color: selDelegate.highlighted ? Theme.bgHover : "transparent"
        }
    }

    popup: Popup {
        y: ctl.height + 4
        width: Math.max(ctl.width, 180)
        padding: 4
        implicitHeight: Math.min(listView.contentHeight + 8, 320)
        background: Rectangle {
            radius: Theme.rMd
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        contentItem: ListView {
            id: listView
            clip: true
            implicitHeight: contentHeight
            model: ctl.popup.visible ? ctl.delegateModel : null
            currentIndex: ctl.highlightedIndex
            ScrollBar.vertical: AppScrollBar {}
        }
    }
}
