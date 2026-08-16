import QtQuick
import QtQuick.Layouts
import ".."

// 微循环步骤指示（3 列 × 2 行网格）
// 用 GridLayout 而非 Flow：Flow 换行后的实际高度会超过 implicitHeight，
// 在 ColumnLayout 中分配高度不足导致内容溢出重叠（真机实测 bug）
GridLayout {
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

    columns: 3
    columnSpacing: 6
    rowSpacing: 6
    flow: GridLayout.LeftToRight

    Repeater {
        model: pills.steps
        delegate: Row {
            Layout.fillWidth: true
            spacing: 4
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
                visible: index % 3 !== 2 && index < pills.steps.length - 1
                text: "→"
                color: "#3A382F"
                font.pixelSize: Theme.fsTiny
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
