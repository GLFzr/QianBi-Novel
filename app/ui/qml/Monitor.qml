import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

ColumnLayout {
    spacing: 0

    signal gotoChapterDetail()

    // ---- 顶栏 ----
    Rectangle {
        Layout.fillWidth: true
        height: 62
        color: Theme.bgPanel
        border.width: 0
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: 12

            Column {
                spacing: 2
                Text {
                    text: bridge.bookTitle
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                }
                Text {
                    text: bridge.bookMeta
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
            }
            Item { Layout.fillWidth: true }
            StageStepper {
                Layout.alignment: Qt.AlignVCenter
                stageKey: bridge.stageKey
                proseProgress: bridge.progressText
            }
            Item { Layout.fillWidth: true }

            AppButton {
                visible: !bridge.isRunning
                text: "▶ 开始"
                kind: "primary"
                onClicked: bridge.startPipeline()
            }
            AppButton {
                visible: bridge.isRunning && !bridge.isPaused
                text: "⏸ 暂停"
                onClicked: bridge.pausePipeline()
            }
            AppButton {
                visible: bridge.isRunning && bridge.isPaused
                text: "▶ 继续"
                kind: "primary"
                onClicked: bridge.resumePipeline()
            }
            AppButton {
                visible: bridge.isRunning
                text: "⏹ 停止"
                kind: "danger"
                onClicked: bridge.stopPipeline()
            }
        }
    }

    // ---- 主区 ----
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 0

        // 章节队列
        Rectangle {
            Layout.preferredWidth: 360
            Layout.fillHeight: true
            color: "transparent"
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "章节队列"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: bridge.progressText
                        color: Theme.textTertiary
                        font.family: Theme.monoFont
                        font.pixelSize: Theme.fsTiny
                    }
                }

                ListView {
                    id: queueList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.chapterModelProp
                    spacing: 4
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: QueueRow {
                        num: model.num
                        title: model.title
                        state: model.state
                        words: model.words
                        note: model.note
                        onOpenChapter: function (n) { bridge.openChapter(n); gotoChapterDetail() }
                        onRewriteChapter: function (n) { bridge.rewriteChapter(n) }
                    }

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                        background: Item {}
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 52
                    radius: 10
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        RowLayout {
                            width: parent.width
                            Text {
                                text: "全书进度"
                                color: Theme.textSecondary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: Math.round(bridge.progressValue * 100) + "%"
                                color: Theme.accent
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.monoFont
                            }
                        }
                        ThinProgress { width: parent.width; value: bridge.progressValue }
                    }
                }
            }
        }

        // 当前任务面板
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: bridge.currentChapterNum > 0
                          ? "第 " + bridge.currentChapterNum + " 章" + (bridge.lastRecord.title ? " · " + bridge.lastRecord.title : "")
                          : (bridge.isRunning ? "准备中…" : "待命")
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: bridge.slotsText
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
            }

            StepPills {
                currentStep: bridge.currentStepKey
                running: bridge.isRunning && !bridge.isPaused
            }

            // 质量三格（最近一章定稿结果）
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: [
                        { "label": "AI 味 · 阻断", "key": "deslop_blocking", "bad": true },
                        { "label": "审校 · 阻塞", "key": "review_blocking", "bad": true },
                        { "label": "AI 味 · 建议", "key": "deslop_advisory", "bad": false },
                        { "label": "字数", "key": "words", "bad": false }
                    ]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 52
                        radius: 10
                        color: Theme.bgCard
                        border.width: 1
                        border.color: Theme.border
                        Column {
                            anchors.centerIn: parent
                            spacing: 2
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: bridge.lastRecord[modelData.key] !== undefined ? bridge.lastRecord[modelData.key] : "—"
                                color: modelData.bad && bridge.lastRecord[modelData.key] > 0 ? Theme.danger
                                     : modelData.key === "words" ? Theme.success
                                     : Theme.textPrimary
                                font.pixelSize: 18
                                font.family: Theme.monoFont
                            }
                        }
                    }
                }
            }

            LogView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: bridge.logModelProp
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                AppButton {
                    text: "↺ 重写本章"
                    kind: "danger"
                    enabled: !bridge.isRunning && bridge.lastRecord.num !== undefined
                    onClicked: bridge.rewriteChapter(bridge.lastRecord.num)
                }
                AppButton {
                    text: "打开最新一章"
                    enabled: bridge.lastRecord.num !== undefined
                    onClicked: { bridge.openChapter(bridge.lastRecord.num); gotoChapterDetail() }
                }
                Item { Layout.fillWidth: true }
            }
        }
    }

    // ---- 底栏 ----
    Rectangle {
        Layout.fillWidth: true
        height: 30
        color: Theme.bgPanel
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: 14
            Text {
                text: bridge.slotsText
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Text {
                text: "累计 " + bridge.totalTokens.toLocaleString() + " tokens · ≈ " + bridge.estCost
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.monoFont
            }
            Item { Layout.fillWidth: true }
            Text {
                text: bridge.isPaused ? "已暂停 · 进度已保存，可随时续跑" : ""
                color: Theme.accent
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
        }
    }
}
