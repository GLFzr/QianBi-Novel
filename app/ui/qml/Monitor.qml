import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 流水线工作台（三栏布局）
// 左：章节队列  中：写作工作区（当前章状态/质量/操作）  右：运行日志
// ============================================================
ColumnLayout {
    id: monitor
    spacing: 0

    signal gotoChapterDetail()

    // ---- 顶栏 ----
    Rectangle {
        Layout.fillWidth: true
        height: 58
        color: Theme.bgPanel
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 14
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
                text: "📂 项目文件"
                kind: "ghost"
                onClicked: {
                    fileModel.clear()
                    var files = bridge.projectFiles()
                    for (var i = 0; i < files.length; i++) fileModel.append(files[i])
                    fileDialog.open()
                }
            }
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

    // ---- 三栏主区 ----
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 0

        // ========== 左栏：章节队列 ==========
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: "transparent"
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "章节队列"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        font.bold: true
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
                    spacing: 3
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
                        onRewriteChapterWithGuidance: function (n, g) { bridge.rewriteChapterWithGuidance(n, g) }
                    }

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                        background: Item {}
                    }
                }

                // 全书进度
                Rectangle {
                    Layout.fillWidth: true
                    height: 46
                    radius: 10
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 5
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

        // ========== 中栏：写作工作区 ==========
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 14
            spacing: 12

            // 当前章状态卡
            Rectangle {
                Layout.fillWidth: true
                height: stateCol.implicitHeight + 28
                radius: Theme.rCard
                color: Theme.bgCard
                border.width: 1
                border.color: Theme.border

                ColumnLayout {
                    id: stateCol
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Column {
                            spacing: 2
                            Text {
                                text: bridge.currentChapterNum > 0
                                      ? "第 " + bridge.currentChapterNum + " 章" + (bridge.lastRecord.title ? " · " + bridge.lastRecord.title : "")
                                      : (bridge.isRunning ? "准备中…" : "待命")
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: 15
                                font.bold: true
                            }
                            Text {
                                text: bridge.slotsText
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                            }
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
                }
            }

            // 质量四格（最近一章定稿结果）
            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: 8
                rowSpacing: 8

                Repeater {
                    model: [
                        { "label": "AI 味 · 阻断", "key": "deslop_blocking", "bad": true },
                        { "label": "审校 · 阻塞", "key": "review_blocking", "bad": true },
                        { "label": "AI 味 · 建议", "key": "deslop_advisory", "bad": false },
                        { "label": "字数", "key": "words", "bad": false }
                    ]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 56
                        radius: 10
                        color: Theme.bgCard
                        border.width: 1
                        border.color: Theme.border
                        Column {
                            anchors.centerIn: parent
                            spacing: 3
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

            // 快捷操作
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
                    text: "✎ 带指导重写…"
                    enabled: !bridge.isRunning && bridge.lastRecord.num !== undefined
                    onClicked: guidanceDialog.open()
                }
                AppButton {
                    text: "打开最新一章"
                    enabled: bridge.lastRecord.num !== undefined
                    onClicked: { bridge.openChapter(bridge.lastRecord.num); gotoChapterDetail() }
                }
                Item { Layout.fillWidth: true }
            }

            // 提示区（未运行时给操作引导）
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.rCard
                color: "transparent"
                border.width: 1
                border.color: Theme.border
                visible: !bridge.isRunning

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: bridge.lastRecord.num !== undefined
                              ? "点击章节可阅读/编辑，右键可重写；点「开始」从断点续跑"
                              : "点「▶ 开始」启动流水线：设定 → 大纲 → 细纲 → 正文，全程可暂停、可介入"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: bridge.isPaused ? "⏸ 已暂停 · 进度已保存，处理完问题后点「继续」" : ""
                        color: Theme.accent
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                    }
                }
            }
        }

        // ========== 右栏：运行日志 ==========
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: "transparent"
            Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "运行日志"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: "清空"
                        kind: "ghost"
                        height: 22
                        onClicked: bridge.logModelProp.clear()
                    }
                }

                LogView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.logModelProp
                }
            }
        }
    }

    // ---- 底栏 ----
    Rectangle {
        Layout.fillWidth: true
        height: 28
        color: Theme.bgPanel
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: 14
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

    // ---- 带指导重写对话框 ----
    Dialog {
        id: guidanceDialog
        modal: true
        anchors.centerIn: parent
        width: 460
        padding: 18
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "带指导重写 第 " + (bridge.lastRecord.num || "?") + " 章"
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 18
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                text: "写下重写要求（注入正文生成 prompt），点「重写」后点「开始」从本章续跑："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                wrapMode: Text.Wrap
                width: parent.width
            }
            TextArea {
                id: guidanceArea
                width: parent.width
                height: 110
                placeholderText: "如：女主这章不要下线；打脸段落写在场配角反应；结尾钩子指向拍卖会…"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
                selectByMouse: true
                background: Rectangle {
                    radius: Theme.rBtn
                    color: Theme.bgHover
                    border.width: 1
                    border.color: Theme.border
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: guidanceDialog.close()
            }
            AppButton {
                text: "重写"
                kind: "primary"
                onClicked: {
                    bridge.rewriteChapterWithGuidance(bridge.lastRecord.num, guidanceArea.text)
                    guidanceArea.text = ""
                    guidanceDialog.close()
                }
            }
        }
    }

    // ---- 项目文件浏览/编辑对话框 ----
    Dialog {
        id: fileDialog
        modal: true
        anchors.centerIn: parent
        width: 880
        height: 580
        padding: 0
        property string currentRel: ""
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgPanel
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "项目文件 · " + bridge.bookTitle
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 18
        }

        ListModel { id: fileModel }

        contentItem: RowLayout {
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 240
                Layout.fillHeight: true
                color: Theme.bgCard
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

                ListView {
                    id: fileList
                    anchors.fill: parent
                    anchors.margins: 8
                    model: fileModel
                    spacing: 2
                    clip: true
                    delegate: Rectangle {
                        width: ListView.view.width
                        height: 34
                        radius: 6
                        color: fileList.currentIndex === index ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12) : "transparent"
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            spacing: 6
                            Text {
                                text: model.dir
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            Text {
                                text: model.name
                                color: fileList.currentIndex === index ? Theme.accent : Theme.textPrimary
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.uiFont
                                elide: Text.ElideRight
                                width: 150
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                fileList.currentIndex = index
                                fileEditor.text = bridge.readProjectFile(model.rel)
                                fileDialog.currentRel = model.rel
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: fileDialog.currentRel !== "" ? fileDialog.currentRel : "选择左侧文件"
                        color: Theme.textSecondary
                        font.family: Theme.monoFont
                        font.pixelSize: Theme.fsTiny
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: fileEditor.text ? "字数：" + fileEditor.text.replace(/\s/g, "").length : ""
                        color: Theme.textTertiary
                        font.family: Theme.monoFont
                        font.pixelSize: Theme.fsTiny
                    }
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    TextArea {
                        id: fileEditor
                        color: Theme.textPrimary
                        font.family: Theme.serifFont
                        font.pixelSize: 15
                        wrapMode: Text.Wrap
                        selectByMouse: true
                        background: Rectangle { color: Theme.bgLog; radius: 8 }
                        padding: 12
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: "保存修改"
                        kind: "primary"
                        enabled: fileDialog.currentRel !== ""
                        onClicked: bridge.saveProjectFile(fileDialog.currentRel, fileEditor.text)
                    }
                }
            }
        }
    }
}
