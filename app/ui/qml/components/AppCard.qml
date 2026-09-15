import QtQuick
import QtQuick.Layouts
import ".."

Rectangle {
    default property alias content: inner.data
    property int pad: 14
    // U-08：浮起分级。0=平面卡片（现状默认，视觉零变化）/ 1=悬浮影 / 2=弹层影+提亮面
    property int elevation: 0
    // WP-09：inner 由 Item 改 ColumnLayout——普通 Item 不聚合子项 implicit 尺寸，
    // 0 实例时从未暴露（首实例 gateBlock 会塌成 0 高）；内容间距可调
    property real contentSpacing: 8

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
        color: Theme.shadowSoft1
        z: -1
    }
    Rectangle {
        visible: parent.elevation >= 2
        anchors.fill: parent
        anchors.topMargin: 5
        radius: parent.radius
        color: Theme.shadowSoft2
        z: -2
    }

    implicitWidth: inner.implicitWidth + pad * 2
    implicitHeight: inner.implicitHeight + pad * 2

    ColumnLayout {
        id: inner
        anchors.fill: parent
        anchors.margins: pad
        spacing: contentSpacing
    }
}
