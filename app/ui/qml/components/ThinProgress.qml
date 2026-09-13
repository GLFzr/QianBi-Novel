import QtQuick
import ".."

Rectangle {
    id: bar
    property real value: 0          // 0..1
    property color fill: Theme.accent
    property bool indeterminate: false   // v1.2 动效：章内运行期间扫动，区分"在跑"与"卡死"

    height: 4
    radius: 2
    color: Theme.bgActive
    clip: true

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, bar.value))
        height: parent.height
        radius: 2
        color: bar.fill
        opacity: bar.indeterminate ? 0.45 : 1.0
        Behavior on width { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: Theme.durNormal } }
    }

    // 不确定态：30% 宽滑块周期扫过（render 线程 XAnimator，Python 高频 emit 时仍顺滑）
    Rectangle {
        id: slider
        visible: bar.indeterminate && Theme.motionOK
        width: parent.width * 0.3
        height: parent.height
        radius: 2
        color: bar.fill
        XAnimator on x {
            running: bar.indeterminate && Theme.motionOK
            loops: Animation.Infinite
            from: -bar.width * 0.3
            to: bar.width
            duration: Theme.durIndet
            easing.type: Easing.InOutQuad
        }
    }
}
