import QtQuick
import ".."

// ============================================================
// AppStatTile · 指标瓦片（标签 + 数值 + 可选 3px 细条）
// 取代旧的高饱和纯色大块：数字是主角，语义色只出现在细条/数值上。
// ============================================================
Rectangle {
    id: root
    property string label: ""
    property string value: "—"
    property color valueColor: Theme.textPrimary
    property real ratio: -1        // 0..1，<0 不显示细条
    property color barColor: Theme.accent

    radius: Theme.rMd
    color: Theme.bgCard
    border.width: 1
    border.color: Theme.border
    implicitWidth: 120
    implicitHeight: ratio >= 0 ? 58 : 46

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 3

        Text {
            text: root.label
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
        }
        Text {
            text: root.value
            color: root.valueColor
            font.family: Theme.monoFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
        }
        Rectangle {
            visible: root.ratio >= 0
            width: parent.width
            height: 3
            radius: 1.5
            color: Theme.bgActive
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, root.ratio))
                height: parent.height
                radius: 1.5
                color: root.barColor
                Behavior on width { NumberAnimation { duration: 150 } }
            }
        }
    }
}
