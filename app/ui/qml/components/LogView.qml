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

        onCountChanged: Qt.callLater(function () { list.positionViewAtEnd() })

        delegate: Row {
            spacing: 8
            width: list.width
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
                opacity: 0.8
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
