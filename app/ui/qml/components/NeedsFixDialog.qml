import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// 待修章节汇总对话框：流水线检出的全部问题章节集中呈现
// 每章：查看问题 / 修复本章 / 打开；全书：一键修复全部
// 修复前自动快照「修复前备份」，复扫未改善则保留原稿
// ============================================================
Dialog {
    id: needsFixDialog
    objectName: "needsFixDialog"
    title: "待修章节"
    modal: true
    standardButtons: Dialog.NoButton
    width: Math.min(800, parent.width * 0.92)
    height: Math.min(620, parent.height * 0.9)
    anchors.centerIn: parent
    background: DialogBg {}

    property var chapters: []

    function refresh() {
        chapters = bridge.needsFixChapters()
    }

    onOpened: refresh()

    Connections {
        target: bridge
        function onNeedsFixChanged() {
            if (needsFixDialog.opened) needsFixDialog.refresh()
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        // 头部
        Rectangle {
            Layout.fillWidth: true
            height: 48
            color: Theme.bgPanel
            radius: Theme.rCard
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 8
                Text {
                    text: "待修章节汇总（" + needsFixDialog.chapters.length + " 章）"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    Layout.fillWidth: true
                }
                AppBadge {
                    visible: bridge.repairRunning
                    text: "修复中…"
                    tint: Theme.accent
                    pulse: true
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 14
            Layout.rightMargin: 14
            Layout.topMargin: 8
            text: "流水线审校检出以下章节存在阻塞级问题。可逐章处理，也可一键按全部检出问题定向修复（修复前自动备份原稿，复扫未改善会保留原稿）。"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.Wrap
        }

        // 章节列表
        ListView {
            id: nfList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 8
            clip: true
            spacing: 6
            visible: needsFixDialog.chapters.length > 0
            model: needsFixDialog.chapters
            delegate: Rectangle {
                required property var modelData
                width: nfList.width
                height: 54
                radius: Theme.rCard
                color: Theme.bgCard
                border.width: 1
                border.color: modelData.needHuman ? Theme.info : Theme.danger
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 10
                    spacing: 8
                    Column {
                        spacing: 2
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        Text {
                            width: parent.width
                            text: "第 " + modelData.num + " 章"
                                  + (modelData.title ? " · " + modelData.title : "")
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.blocking + " 处阻塞"
                                  + (modelData.advisory ? " · " + modelData.advisory + " 处建议" : "")
                                  + (modelData.needHuman ? " · 已标人工" : "")
                            color: Theme.textTertiary
                            font.family: Theme.monoFont
                            font.pixelSize: Theme.fsTiny
                        }
                    }
                    AppBadge {
                        visible: !!modelData.verdict
                        text: modelData.verdict || ""
                        tint: modelData.verdict === "REJECT-HARD" ? Theme.danger : Theme.info
                    }
                    AppButton {
                        text: "查看问题"
                        height: 26
                        enabled: !bridge.repairRunning
                        onClicked: bridge.showReviewIssues(modelData.num)
                    }
                    AppButton {
                        text: "修复本章"
                        kind: "primary"
                        height: 26
                        enabled: !bridge.repairRunning
                        onClicked: bridge.repairChapters([modelData.num])
                    }
                    AppButton {
                        text: "打开"
                        height: 26
                        onClicked: {
                            bridge.openChapter(modelData.num)
                            needsFixDialog.close()
                        }
                    }
                }
            }
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                background: Item {}
            }
        }

        // 空状态
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: needsFixDialog.chapters.length === 0
            Text {
                anchors.centerIn: parent
                text: "没有待修章节"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
            }
        }

        // 底部：进度 + 一键修复 + 关闭
        Rectangle {
            Layout.fillWidth: true
            height: 56
            color: Theme.bgPanel
            radius: Theme.rCard
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                Text {
                    text: bridge.repairStatus
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                AppButton {
                    text: "一键修复全部"
                    kind: "primary"
                    height: 32
                    enabled: !bridge.repairRunning && needsFixDialog.chapters.length > 0
                    onClicked: bridge.repairAll()
                }
                AppButton {
                    text: "关闭"
                    height: 32
                    onClicked: needsFixDialog.close()
                }
            }
        }
    }
}
