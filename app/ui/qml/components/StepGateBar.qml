import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// StepGateBar · 步骤决策门（人 AI 共写指挥台）
// 流水线每一步完成 → 停在决策门：看产物、可选想法、继续或回退重做
// 三种决策：空+继续=直接走 · 想法+继续=带想法走 · 想法+回退=带想法重做
// ============================================================
Rectangle {
    id: gateBar
    objectName: "gateBar"
    visible: opacity > 0.01 && height > 1
    width: parent ? parent.width : 0
    height: waiting ? gateCol.implicitHeight + 18 : 0
    // 红线⑦：height 属 relayout 动画禁用——出显改为纯 opacity（WP-09）
    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
    opacity: waiting ? 1.0 : 0.0
    radius: Theme.rCard
    color: Theme.bgCard
    border.width: 1
    border.color: Theme.accent
    clip: true

    property string gateKey: ""
    property int gateChapter: 0
    property string gateSummary: ""
    property bool waiting: false
    // L2-09/10/12 免裁决半步：门条显示「这门拦什么/能做什么」——静态表，绑定算一次即正确
    property var gateMetaMap: {
        var m = {}
        var l = bridge.gateMetaList()
        for (var i = 0; i < l.length; i++)
            m[l[i].key] = l[i]
        return m
    }
    property bool rollbackable: gateKey !== "G5L"

    function showGate(key, chapter, summary) {
        gateKey = key
        gateChapter = chapter
        gateSummary = summary
        ideaInput.text = ""
        waiting = true
        ideaInput.forceActiveFocus()
    }

    function doNext() {
        if (!waiting) return
        bridge.resolveStepGate("next", ideaInput.text)
        waiting = false
    }

    function doReturn() {
        if (!waiting || !rollbackable) return
        bridge.resolveStepGate("return", ideaInput.text)
        waiting = false
    }

    ColumnLayout {
        id: gateCol
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            AppIcon {
                name: "pause"
                size: 14
                color: Theme.accent
                Layout.alignment: Qt.AlignVCenter
            }
            Text {
                text: "决策门 " + gateKey + (gateChapter ? " · 第" + gateChapter + "章" : "")
                color: Theme.accent
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                font.bold: true
            }
            Text {
                Layout.fillWidth: true
                text: gateSummary
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                // L2-11：多违规不再只露第一条——换行呈现（上限 3 条 + 余量计数）
                wrapMode: Text.Wrap
                maximumLineCount: 4
            }
            Text {
                id: waitText
                text: "等待你的决定…"
                color: Theme.accent
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                // v1.2：循环动画改 render 线程 Animator + motionOK 总闸（减少动态）
                SequentialAnimation {
                    running: gateBar.waiting && Theme.motionOK
                    loops: Animation.Infinite
                    OpacityAnimator { target: waitText; from: 1; to: 0.3; duration: Theme.durLoop / 2 }
                    OpacityAnimator { target: waitText; from: 0.3; to: 1; duration: Theme.durLoop / 2 }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: gateMetaMap[gateKey] !== undefined
            text: "拦哪条：" + (gateMetaMap[gateKey] ? gateMetaMap[gateKey].desc : "")
                  + (gateMetaMap[gateKey] && gateMetaMap[gateKey].wired ? "" : "（未接线）")
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            TextField {
                id: ideaInput
                Layout.fillWidth: true
                placeholderText: gateKey === "G8"
                    ? "人工审校：每行一条**阻断级**问题；留空 = 放行"
                    : "想法 / 修改意见（可留空）"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                selectByMouse: true
                background: Rectangle {
                    radius: Theme.rBtn
                    color: Theme.bgHover
                    border.width: 1
                    border.color: ideaInput.activeFocus ? Theme.accent : Theme.border
                }
                Keys.onReturnPressed: gateBar.doNext()
                Keys.onEnterPressed: gateBar.doNext()
            }
            AppButton {
                text: "继续"
                kind: "primary"
                height: 30
                enabled: gateBar.waiting
                onClicked: gateBar.doNext()
                ToolTip.visible: hovered
                ToolTip.text: "继续：空想法=直接过门，有想法=想法带进下一步"
            }
            AppButton {
                text: "回退"
                kind: "danger"
                height: 30
                enabled: gateBar.waiting && gateBar.rollbackable
                visible: gateBar.rollbackable
                onClicked: gateBar.doReturn()
                ToolTip.visible: hovered
                ToolTip.text: "回退：本步产物先归档再重做（G5 软门无产物，只带想法重来）"
            }
        }

        Text {
            Layout.fillWidth: true
            text: "快捷键：回车=继续 · Ctrl+回车=带想法继续 · R=回退重做（G5 软门无回退）"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
        }
    }
}