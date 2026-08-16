import QtQuick
import ".."

Flow {
    id: pills
    property string currentStep: ""     // assemble/draft/scan/deslop/review/finalize（空=未开始）
    property bool running: false

    readonly property var steps: [
        { "key": "assemble", "label": "上下文" },
        { "key": "draft", "label": "草稿" },
        { "key": "scan", "label": "扫描" },
        { "key": "deslop", "label": "去味" },
        { "key": "review", "label": "审校" },
        { "key": "finalize", "label": "定稿" }
    ]

    spacing: 5
    flow: Flow.LeftToRight

    Repeater {
        model: pills.steps
        delegate: Row {
            spacing: 5
            AppBadge {
                readonly property int myIdx: index
                readonly property int curIdx: pills.steps.findIndex(function (s) { return s.key === pills.currentStep })
                text: modelData.label + (myIdx < curIdx || (!pills.running && pills.currentStep === "finalize" && myIdx <= curIdx) ? " ✓"
                       : myIdx === curIdx && pills.running ? " ▶" : "")
                tint: myIdx < curIdx ? Theme.success
                    : myIdx === curIdx && pills.running ? Theme.accent
                    : Theme.muted
                pulse: myIdx === curIdx && pills.running
            }
            Text {
                visible: index < pills.steps.length - 1
                text: "→"
                color: "#3A382F"
                font.pixelSize: Theme.fsTiny
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
