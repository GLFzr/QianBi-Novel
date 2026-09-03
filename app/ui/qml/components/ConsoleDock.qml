import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// ConsoleDock · Agent Console（T4.3 M1+M2）
// 中列常驻：思考链按 槽位×阶段×章 分组留存（随章结束不清空）+ 对话区
// （人的想法 / 门摘要 / Agent 回执）+ 输入框（门等待中=带想法继续，否则沉淀想法）
// 两态：折叠 24px 把手 / 展开 280px 面板（plan_agent_console_v3 §1.4）
// ============================================================
Rectangle {
    id: consoleDock
    objectName: "consoleDock"
    property bool expanded: bridge ? bridge.consoleExpanded : false
    // 必须走 Layout 附加属性：本件是 RowLayout 的直接子项，只给裸 width 时布局
    // 永远按折叠宽记账，展开的那 280px 会被相邻不透明面板盖住（看起来像「被遮挡」）
    Layout.preferredWidth: expanded ? 280 : 24
    Layout.minimumWidth: Layout.preferredWidth
    Layout.maximumWidth: Layout.preferredWidth
    Layout.fillHeight: true
    color: Theme.bgPanel
    clip: true

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

    // ---- 折叠态：细窄把手 ----
    ColumnLayout {
        anchors.fill: parent
        visible: !consoleDock.expanded
        spacing: 10

        Item { Layout.fillHeight: true }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "‹"
            color: bridge && bridge.consoleExpanded ? Theme.accent : Theme.textSecondary
            font.pixelSize: 14
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "C\no\nn\ns\no\nl\ne"
            color: Theme.textTertiary
            font.pixelSize: 10
            font.letterSpacing: 2
        }
        Item { Layout.fillHeight: true }
    }
    MouseArea {
        anchors.fill: parent
        visible: !consoleDock.expanded
        cursorShape: Qt.PointingHandCursor
        onClicked: bridge && bridge.setConsoleExpanded(true)
    }

    // ---- 展开态：思考链 + 对话区 + 输入 ----
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        visible: consoleDock.expanded
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Agent Console"
                color: Theme.textPrimary
                font.pixelSize: 12
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            AppButton {
                text: "×"
                height: 20
                onClicked: bridge && bridge.setConsoleExpanded(false)
            }
        }

        // 思考链（M1：留存可回看，当前章优先）
        Text {
            text: "思考链（留存·当前章优先）"
            color: Theme.textTertiary
            font.pixelSize: 10
        }
        ListView {
            id: thinkingList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: bridge ? bridge.consoleThinkingGroups : []
            delegate: Rectangle {
                required property var modelData
                width: thinkingList.width
                height: gCol.implicitHeight + 12
                radius: Theme.rCard
                color: Theme.bgCard
                border.width: 1
                border.color: modelData.is_current ? Theme.accent : Theme.border
                ColumnLayout {
                    id: gCol
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 2
                    Text {
                        text: (modelData.is_current ? "● " : "○ ")
                              + modelData.slot + " · " + modelData.stage
                              + (modelData.num ? " · 第" + modelData.num + "章" : "")
                        color: modelData.is_current ? Theme.accent : Theme.textTertiary
                        font.pixelSize: 10
                        font.family: Theme.monoFont
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: modelData.text
                        color: Theme.textSecondary
                        font.pixelSize: 10
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                    }
                }
            }
        }

        // 对话区（M2：想法/门摘要/回执镜像，落盘 pipeline_debug/console/）
        Text {
            text: "对话"
            color: Theme.textTertiary
            font.pixelSize: 10
        }
        ListView {
            id: dialogueList
            Layout.fillWidth: true
            Layout.preferredHeight: parent.height * 0.34
            clip: true
            spacing: 4
            model: bridge ? bridge.consoleDialogue : []
            delegate: Text {
                required property var modelData
                width: dialogueList.width
                text: {
                    var tag = modelData.kind === "user" ? "我"
                            : modelData.kind === "gate" ? "门"
                            : "Agent"
                    return "[" + modelData.ts + "] " + tag + "：" + modelData.text
                }
                color: modelData.kind === "user" ? Theme.textPrimary
                     : modelData.kind === "gate" ? Theme.accent
                     : Theme.textSecondary
                font.pixelSize: 10
                wrapMode: Text.WrapAnywhere
            }
        }

        // 输入框（门等待中=带想法继续；否则沉淀为下一章想法）
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            TextField {
                id: consoleInput
                objectName: "consoleInput"
                Layout.fillWidth: true
                placeholderText: "想法 / 给 Agent 的指令…"
                font.pixelSize: 11
                color: Theme.textPrimary
                background: Rectangle {
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: consoleInput.activeFocus ? Theme.accent : Theme.border
                }
                onAccepted: {
                    if (text.trim() !== "") {
                        bridge.consoleSubmit(text)
                        text = ""
                    }
                }
            }
            AppButton {
                text: "发送"
                onClicked: {
                    if (consoleInput.text.trim() !== "") {
                        bridge.consoleSubmit(consoleInput.text)
                        consoleInput.text = ""
                    }
                }
            }
        }
    }
}
