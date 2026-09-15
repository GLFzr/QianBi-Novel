import QtQuick
import QtQuick.Controls.Basic
import ".."

Rectangle {
    id: logBox
    property alias model: list.model

    radius: Theme.rLg
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
                width: 3
                height: 10
                radius: 2
                anchors.verticalCenter: parent.verticalCenter
                visible: model.level !== "info"
                color: Theme.levelColor(model.level)
                // N-11 红线修正：delegate 内禁 width 动画（牵连 Row 重排）——改 opacity 渐入
                opacity: 0
                Component.onCompleted: opacity = 0.8
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

        ScrollBar.vertical: AppScrollBar {}
    }
}
