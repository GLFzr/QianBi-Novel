import QtQuick
import ".."

Row {
    id: stepper
    property string stageKey: "init"        // setting/outline/ch_outline/prose/done
    property string proseProgress: ""       // 如 "41/120"

    readonly property var stages: [
        { "key": "setting", "label": "设定" },
        { "key": "outline", "label": "大纲" },
        { "key": "ch_outline", "label": "细纲" },
        { "key": "prose", "label": "正文" },
        { "key": "done", "label": "完本" }
    ]
    readonly property var order: ["setting", "outline", "ch_outline", "prose", "done"]

    spacing: 0

    Repeater {
        model: stepper.stages
        delegate: Row {
            spacing: 0

            // 阶段圆点 + 标签
            Row {
                spacing: 5
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    readonly property int myIdx: stepper.order.indexOf(modelData.key)
                    readonly property int curIdx: stepper.order.indexOf(stepper.stageKey)
                    width: 7; height: 7; radius: 4
                    anchors.verticalCenter: parent.verticalCenter
                    color: myIdx < curIdx ? Theme.success
                         : myIdx === curIdx ? Theme.accent
                         : Theme.borderStrong
                    Behavior on color { ColorAnimation { duration: Theme.durNormal } }
                    // v1.2 动效：阶段完成瞬间一次性弹跳（scale 1→1.5→1）
                    onMyIdxChanged: if (myIdx < stepper.order.indexOf(stepper.stageKey)) popAnim.restart()
                    SequentialAnimation {
                        id: popAnim
                        NumberAnimation { target: parent; property: "scale"; to: 1.5; duration: Theme.durFast; easing.type: Easing.OutCubic }
                        NumberAnimation { target: parent; property: "scale"; to: 1.0; duration: Theme.durNormal; easing.type: Easing.InOutQuad }
                    }
                }
                Text {
                    readonly property int myIdx: stepper.order.indexOf(modelData.key)
                    readonly property int curIdx: stepper.order.indexOf(stepper.stageKey)
                    text: modelData.key === "prose" && curIdx === 3 && stepper.proseProgress !== ""
                          ? "正文 " + stepper.proseProgress : modelData.label
                    color: myIdx < curIdx ? Theme.success
                         : myIdx === curIdx ? Theme.accent
                         : Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.bold: myIdx === curIdx
                }
            }

            // 细线连接（非最后一项）：双层结构，完成的段点亮（电流推进叙事）
            Rectangle {
                visible: index < stepper.stages.length - 1
                readonly property bool lit: stepper.order.indexOf(modelData.key)
                    < stepper.order.indexOf(stepper.stageKey)
                width: 18
                height: 1
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.border
                Rectangle {
                    width: parent.lit ? parent.width : 0
                    height: parent.height
                    color: Theme.success
                    Behavior on width { NumberAnimation { duration: Theme.durSlow; easing: Theme.easeOut } }
                }
            }
        }
    }
}
