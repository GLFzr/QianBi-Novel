import QtQuick
import ".."

Rectangle {
    default property alias content: inner.data
    property int pad: 14

    radius: Theme.rCard
    color: Theme.bgCard
    border.width: 1
    border.color: Theme.border

    implicitWidth: inner.implicitWidth + pad * 2
    implicitHeight: inner.implicitHeight + pad * 2

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: pad
    }
}
