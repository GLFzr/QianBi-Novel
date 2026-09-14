import QtQuick
import ".."

Rectangle {
    default property alias content: inner.data
    property int pad: 14
    // U-08：浮起分级。0=平面卡片（现状默认，视觉零变化）/ 1=悬浮影 / 2=弹层影+提亮面
    property int elevation: 0

    radius: Theme.rCard
    color: elevation >= 2 ? Theme.bgRaise : Theme.bgCard
    border.width: 1
    border.color: Theme.border

    // 手绘柔影（§5.4 红线①：多层 Rectangle，不用 MultiEffect；elevation=0 时零开销）
    Rectangle {
        visible: parent.elevation >= 1
        anchors.fill: parent
        anchors.topMargin: 2
        radius: parent.radius
        color: Qt.rgba(Theme.shadowColor.r, Theme.shadowColor.g, Theme.shadowColor.b, Theme.shE1Alpha)
        z: -1
    }
    Rectangle {
        visible: parent.elevation >= 2
        anchors.fill: parent
        anchors.topMargin: 5
        radius: parent.radius
        color: Qt.rgba(Theme.shadowColor.r, Theme.shadowColor.g, Theme.shadowColor.b, Theme.shE2Alpha)
        z: -2
    }

    implicitWidth: inner.implicitWidth + pad * 2
    implicitHeight: inner.implicitHeight + pad * 2

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: pad
    }
}
