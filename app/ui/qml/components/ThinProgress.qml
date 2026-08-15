import QtQuick
import ".."

Rectangle {
    id: bar
    property real value: 0          // 0..1
    property color fill: Theme.accent

    height: 3
    radius: 99
    color: Theme.bgHover

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, bar.value))
        height: parent.height
        radius: 99
        color: bar.fill
        Behavior on width { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
    }
}
