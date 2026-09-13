import QtQuick
import QtQuick.Controls.Basic
import ".."

Rectangle {
    id: logBox
    property alias model: list.model

    radius: 10
    color: Theme.bgLog
    border.width: 1
    border.color: Theme.border
    clip: true

    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 8
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds

        // v1.2 动效：贴底才自动跟随（上翻回看时新行不再把视线顶走），回到底部自动恢复
        property bool follow: true
        onContentYChanged: follow = atYEnd || dragging
        onCountChanged: if (follow) Qt.callLater(function () { list.positionViewAtEnd() })

        delegate: Row {
            spacing: 8
            width: list.width
            // v1.2 动效：新行渐入
            opacity: 0
            Component.onCompleted: opacity = 1
            Behavior on opacity { NumberAnimation { duration: Theme.durNormal } }
            Text {
                text: model.time
                color: Theme.textTertiary
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsTiny
                width: 72
                elide: Text.ElideRight
            }
            Rectangle {
                width: model.level !== "info" ? 3 : 0
                height: 10
                radius: 2
                anchors.verticalCenter: parent.verticalCenter
                visible: model.level !== "info"
                color: Theme.levelColor(model.level)
                opacity: 0.8
                // v1.2 动效：warn/error 色条入场展开（0→3）
                Behavior on width { NumberAnimation { duration: Theme.durNormal; easing: Theme.easeOut } }
                Behavior on opacity { NumberAnimation { duration: Theme.durNormal } }
            }
            Text {
                width: list.width - 100
                text: model.text
                color: Theme.levelColor(model.level)
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
        }

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle {
                implicitWidth: 4
                radius: 2
                color: Theme.bgHover
            }
            background: Item {}
        }
    }
}
