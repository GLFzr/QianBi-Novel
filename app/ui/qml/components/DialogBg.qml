import QtQuick
import ".."

// Dialog 背景 · 主体 + 多层假投影（现代桌面弹窗的 box-shadow）
Item {
    id: root

    // 主体
    Rectangle {
        anchors.fill: parent
        radius: Theme.rCard
        color: Theme.bgCard
        border.width: 1
        border.color: Theme.borderStrong
    }

    // 三层柔影（越界绘制，Popup 不裁剪 background）
    Rectangle { x: -4; y: -2; width: parent.width + 8; height: parent.height + 5
                radius: Theme.rCard + 3; color: "#2E000000"; z: -1 }
    Rectangle { x: -10; y: -6; width: parent.width + 20; height: parent.height + 13
                radius: Theme.rCard + 6; color: "#24000000"; z: -2 }
    Rectangle { x: -20; y: -14; width: parent.width + 40; height: parent.height + 30
                radius: Theme.rCard + 12; color: "#1A000000"; z: -3 }
}
