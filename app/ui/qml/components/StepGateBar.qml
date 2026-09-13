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
    Behavior on height { NumberAnimation { duration: Theme.durNormal; easing: Theme.easeOut } }
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
                elide: Text.ElideRight
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

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            TextField {
                id: ideaInput
                Layout.fillWidth: true
                placeholderText: "对这一步的想法 / 修改意见（留空直接继续；写了想法再按 继续=带想法走，回退=带想法重做）…"
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
                ToolTip.text: "回车 · 空想法=直接继续，有想法=带想法继续"
            }
            AppButton {
                text: "回退"
                kind: "danger"
                height: 30
                enabled: gateBar.waiting && gateBar.rollbackable
                visible: gateBar.rollbackable
                onClicked: gateBar.doReturn()
                ToolTip.visible: hovered
                ToolTip.text: "R · 带想法回退重做本步（产物先归档，正文走版本安全网）"
            }
        }

        Text {
            Layout.fillWidth: true
            text: "快捷键：回车=继续 · Ctrl+回车=带想法继续 · R=回退重做（G5 软门无回退）"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsMicro
        }
    }
}