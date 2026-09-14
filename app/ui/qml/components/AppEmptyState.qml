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
        id: emptyIcon
        name: root.iconName
        size: 40   // U-20：28→40 提升空态可见性
        color: Theme.textTertiary
        opacity: 0.75
        anchors.horizontalCenter: parent.horizontalCenter
        SequentialAnimation on opacity {
            running: root.visible && Theme.motionOK
            loops: Animation.Infinite
            OpacityAnimator { from: 0.75; to: 0.45; duration: Theme.durLoop }
            OpacityAnimator { from: 0.45; to: 0.75; duration: Theme.durLoop }
        }
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
