import QtQuick
import ".."

// ============================================================
// AppDialogTitle · 弹窗标题（大标题 + 可选弱化副题）
// 统一弹窗头：强制换行，长标题/长书名不再画出弹窗边缘。
// 用法：header: AppDialogTitle { title: "…"; subtitle: "…" }
// ============================================================
Column {
    id: root
    property string title: ""
    property string subtitle: ""
    readonly property int pad: 14
    spacing: 3

    Item { height: 4; width: 1 }
    Text {
        x: root.pad
        width: root.width - 2 * root.pad
        text: root.title
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTitle
        font.bold: true
        wrapMode: Text.Wrap
    }
    Text {
        visible: root.subtitle !== ""
        x: root.pad
        width: root.width - 2 * root.pad
        text: root.subtitle
        color: Theme.textSecondary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTiny
        wrapMode: Text.Wrap
    }
    Item { height: 6; width: 1 }
}
