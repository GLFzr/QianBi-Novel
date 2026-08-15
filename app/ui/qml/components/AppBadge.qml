import QtQuick
import ".."

Rectangle {
    id: badge
    property string text: ""
    property color tint: Theme.muted
    property bool pulse: false

    implicitWidth: label.implicitWidth + 18
    implicitHeight: 22
    radius: Theme.rBadge
    color: Qt.rgba(tint.r, tint.g, tint.b, 0.13)

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.text
        color: badge.tint
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTiny
    }

    SequentialAnimation on opacity {
        running: badge.pulse
        loops: Animation.Infinite
        NumberAnimation { to: 0.45; duration: 600; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
    }
}
