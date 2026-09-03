import QtQuick
import ".."

// ============================================================
// AppEmptyState · 空态（图标 + 标题 + 弱化说明）
// 消灭「死黑大区」：任何空列表/空详情区都应给出引导。
// 可选动作：把 AppButton 作为子项追加即可，Column 自动排列。
// ============================================================
Column {
    id: root
    property string iconName: "spark"
    property string title: ""
    property string hint: ""
    spacing: 6

    AppIcon {
        name: root.iconName
        size: 28
        color: Theme.textTertiary
        anchors.horizontalCenter: parent.horizontalCenter
    }
    Text {
        visible: root.title !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.title
        color: Theme.textSecondary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsSmall
    }
    Text {
        visible: root.hint !== ""
        width: Math.min(implicitWidth * 1.4, 300)
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.hint
        color: Theme.textTertiary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTiny
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
    }
}
