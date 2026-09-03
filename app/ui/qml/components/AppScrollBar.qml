import QtQuick
import QtQuick.Controls.Basic
import ".."

// ============================================================
// AppScrollBar · 统一滚动条（细轨 + 悬停加深）
// 用法：ScrollView/Flickable 的 ScrollBar.vertical: AppScrollBar {}
// ============================================================
ScrollBar {
    id: ctl
    policy: ScrollBar.AsNeeded
    minimumSize: 0.08
    contentItem: Rectangle {
        implicitWidth: 6
        radius: 3
        color: ctl.pressed ? Theme.borderStrong
             : ctl.hovered ? Theme.borderStrong
             : Theme.border
        Behavior on color { ColorAnimation { duration: 110 } }
    }
    background: Item {}
}
