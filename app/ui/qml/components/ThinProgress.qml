import QtQuick
import ".."

Rectangle {
    id: bar
    property real value: 0          // 0..1
    property color fill: Theme.accent

    height: 4
    radius: 2
    color: Theme.bgActive

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, bar.value))
        height: parent.height
        radius: 2
        color: bar.fill
        Behavior on width { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
    }
}
