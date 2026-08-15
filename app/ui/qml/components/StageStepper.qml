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
            Text {
                visible: index < stepper.stages.length - 1
                text: " ── "
                color: "#3A382F"
                font.pixelSize: Theme.fsSmall
            }
        }
    }
}
