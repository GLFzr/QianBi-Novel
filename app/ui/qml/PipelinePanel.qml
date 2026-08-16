import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// 流水线控制面板：阶段进度 + 主控制 + 质量格 + 最近定稿
Item {
    id: pipeline

    signal openChapter(int num)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // 头部
        Rectangle {
            Layout.fillWidth: true
            height: 66
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 3
                Text {
                    text: bridge.bookTitle
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    elide: Text.ElideRight
                    width: parent.width
                }
                Text {
                    text: bridge.bookMeta
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                }
            }
        }

        // 阶段步进 + 进度
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            spacing: 8

            StageStepper {
                Layout.fillWidth: true
                stageKey: bridge.stageKey
                proseProgress: bridge.progressText
            }

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "全书进度"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: bridge.progressPercentText
                    color: Theme.accent
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.monoFont
                }
            }
            ThinProgress { Layout.fillWidth: true; value: bridge.progressValue }

            // 主控制按钮
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                AppButton {
                    visible: !bridge.isRunning
                    text: "开始"
                    kind: "primary"
                    Layout.fillWidth: true
                    onClicked: bridge.startPipeline()
                }
                AppButton {
                    visible: bridge.isRunning && !bridge.isPaused
                    text: "暂停"
                    Layout.fillWidth: true
                    onClicked: bridge.pausePipeline()
                }
                AppButton {
                    visible: bridge.isRunning && bridge.isPaused
                    text: "继续"
                    kind: "primary"
                    Layout.fillWidth: true
                    onClicked: bridge.resumePipeline()
                }
                AppButton {
                    visible: bridge.isRunning
                    text: "停止"
                    kind: "danger"
                    Layout.fillWidth: true
                    onClicked: bridge.stopPipeline()
                }
            }

            // 当前章状态
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: bridge.currentChapterNum > 0
                          ? (bridge.isRunning ? "正在写 第 " + bridge.currentChapterNum + " 章"
                                              : "当前 第 " + bridge.currentChapterNum + " 章")
                          : (bridge.isRunning ? "准备中…" : "待命")
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                AppBadge {
                    visible: bridge.lastRecord.num !== undefined
                    text: bridge.lastRecord.status === "pass" ? "已通过" : "待修"
                    tint: bridge.lastRecord.status === "pass" ? Theme.success : Theme.danger
                }
            }

            StepPills {
                currentStep: bridge.currentStepKey
                running: bridge.isRunning && !bridge.isPaused
            }

            // 质量四格（最近一章，2×2）
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 6
                rowSpacing: 6
                Repeater {
                    model: [
                        { "label": "AI味阻断", "key": "deslop_blocking", "bad": true },
                        { "label": "审校阻塞", "key": "review_blocking", "bad": true },
                        { "label": "AI味建议", "key": "deslop_advisory", "bad": false },
                        { "label": "字数", "key": "words", "bad": false }
                    ]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 42
                        radius: 8
                        color: Theme.bgCard
                        border.width: 1
                        border.color: Theme.border
                        Row {
                            anchors.centerIn: parent
                            spacing: 8
                            Text {
                                text: modelData.label
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            Text {
                                text: bridge.lastRecord[modelData.key] !== undefined ? bridge.lastRecord[modelData.key] : "—"
                                color: modelData.bad && bridge.lastRecord[modelData.key] > 0 ? Theme.danger
                                     : modelData.key === "words" ? Theme.success
                                     : Theme.textPrimary
                                font.pixelSize: 15
                                font.family: Theme.monoFont
                                font.bold: true
                            }
                        }
                    }
                }
            }

            // 快捷操作
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                AppButton {
                    text: "重写本章"
                    enabled: !bridge.isRunning && bridge.lastRecord.num !== undefined
                    Layout.fillWidth: true
                    onClicked: bridge.rewriteChapter(bridge.lastRecord.num)
                }
                AppButton {
                    text: "打开最新"
                    enabled: bridge.lastRecord.num !== undefined
                    Layout.fillWidth: true
                    onClicked: { bridge.openChapter(bridge.lastRecord.num); pipeline.openChapter(bridge.lastRecord.num) }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
