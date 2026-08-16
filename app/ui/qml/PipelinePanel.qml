import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 创作驾驶舱（M3）：阶段卡片 + 运行模式 + 主控制 + 质量四格/趋势
// 人定方向：每个阶段可 查看 / 带指导重生成 —— AI 执行前人可介入
// ============================================================
Item {
    id: pipeline

    signal openChapter(int num)
    signal openProjectFile(string rel)

    property var cards: []
    property var trend: []
    property int trendMaxWords: 1
    property string regenKey: ""
    property string regenLabel: ""

    function refresh() {
        cards = bridge.stageCards()
        trend = bridge.qualityTrend()
        var mx = 1
        for (var i = 0; i < trend.length; i++) mx = Math.max(mx, trend[i].words)
        trendMaxWords = mx
    }
    Component.onCompleted: refresh()
    Connections {
        target: bridge
        function onStageKeyChanged() { pipeline.refresh() }
        function onLastRecordChanged() { pipeline.refresh() }
        function onRunningChanged() { pipeline.refresh() }
        function onProjectOpened() { pipeline.refresh() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // 头部（ZCode 式紧凑头：48px · 中标题 · 状态右侧）
        Rectangle {
            Layout.fillWidth: true
            height: 48
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 8
                Column {
                    spacing: 0
                    Layout.fillWidth: true
                    Text {
                        text: bridge.bookTitle === "" ? "流水线" : bridge.bookTitle
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                        elide: Text.ElideRight
                        width: parent.width
                    }
                    Text {
                        visible: bridge.bookMeta !== ""
                        text: bridge.bookMeta
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                        elide: Text.ElideRight
                        width: parent.width
                    }
                }
                // 运行模式切换（自动续写 / 逐步确认）
                Rectangle {
                    id: modeChip
                    visible: bridge.isRunning || bridge.isPaused
                    width: 118; height: 26; radius: 13
                    color: Theme.bgHover
                    border.width: 1
                    border.color: modeChip.stepOn ? Theme.accent : Theme.border
                    property bool stepOn: false
                    Component.onCompleted: modeChip.stepOn = bridge.stepConfirmEnabled()
                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: modeChip.stepOn ? Theme.accent : Theme.muted
                            anchors.verticalCenter: parent.verticalCenter
                            SequentialAnimation on opacity {
                                running: bridge.isRunning && modeChip.stepOn
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.3; duration: 650 }
                                NumberAnimation { to: 1; duration: 650 }
                            }
                        }
                        Text {
                            text: modeChip.stepOn ? "逐步确认中" : "自动续写"
                            color: modeChip.stepOn ? Theme.accent : Theme.textTertiary
                            font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            modeChip.stepOn = !modeChip.stepOn
                            bridge.setStepConfirm(modeChip.stepOn)
                        }
                    }
                    ToolTip.visible: containsMouse
                    ToolTip.text: "点击切换：逐步确认 = 每章定稿后暂停，等你阅读确认再点「继续」"
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: 10
                Layout.margins: 12

                // ---- 阶段卡片（创作驾驶舱：设定→大纲→细纲→正文）----
                Text {
                    text: "创作阶段 · 每阶段可介入"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 6
                    rowSpacing: 6

                    Repeater {
                        model: pipeline.cards
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            height: 92
                            radius: Theme.rCard
                            color: Theme.bgCard
                            border.width: 1
                            border.color: modelData.status === "active" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)
                                     : modelData.status === "done" ? Theme.border : Theme.border
                            Rectangle {
                                anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                                height: 2; radius: 1
                                color: modelData.status === "active" ? Theme.accent
                                     : modelData.status === "done" ? Theme.success : "transparent"
                            }
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 4
                                RowLayout {
                                    spacing: 6
                                    Text {
                                        text: modelData.icon
                                        color: modelData.status === "active" ? Theme.accent
                                             : modelData.status === "done" ? Theme.success : Theme.muted
                                        font.pixelSize: 13
                                    }
                                    Text {
                                        text: modelData.label
                                        color: Theme.textPrimary
                                        font.family: Theme.uiFont
                                        font.pixelSize: Theme.fsSmall
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    AppBadge {
                                        text: modelData.status === "active" ? "进行中"
                                             : modelData.status === "done" ? "完成" : "待开始"
                                        tint: modelData.status === "active" ? Theme.accent
                                             : modelData.status === "done" ? Theme.success : Theme.muted
                                    }
                                }
                                Text {
                                    text: modelData.detail
                                    color: Theme.textTertiary
                                    font.family: Theme.monoFont
                                    font.pixelSize: 10
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                                Row {
                                    spacing: 4
                                    Layout.alignment: Qt.AlignRight
                                    AppButton {
                                        text: "查看"
                                        height: 22
                                        visible: modelData.file !== ""
                                        onClicked: pipeline.openProjectFile(modelData.file)
                                    }
                                    AppButton {
                                        text: "重生成"
                                        height: 22
                                        visible: modelData.key !== "prose"
                                        enabled: !bridge.isRunning
                                        onClicked: {
                                            pipeline.regenKey = modelData.key
                                            pipeline.regenLabel = modelData.label
                                            regenDialog.open()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                StageStepper {
                    Layout.fillWidth: true
                    stageKey: bridge.stageKey
                    proseProgress: bridge.progressText
                }

                // 进度条
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

                // 主控制
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

                StepPills {
                    currentStep: bridge.currentStepKey
                    running: bridge.isRunning && !bridge.isPaused
                }

                // 质量四格
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
                            required property var modelData
                            Layout.fillWidth: true
                            height: 42
                            radius: 8
                            color: Theme.bgCard
                            Rectangle { anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; height: 1
                                       color: Theme.cardHighlight }
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

                // 质量历史趋势（近 20 章：字数柱 + 阻断点）
                Rectangle {
                    Layout.fillWidth: true
                    visible: pipeline.trend.length >= 2
                    radius: Theme.rCard
                    color: Theme.bgCard
                    height: 86
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4
                        Text {
                            text: "质量趋势 · 近 " + pipeline.trend.length + " 章（柱=字数 · 红点=阻断）"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                        }
                        Row {
                            spacing: 3
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Repeater {
                                model: pipeline.trend
                                delegate: Item {
                                    required property var modelData
                                    width: parent.width / pipeline.trend.length - 3
                                    height: parent.height
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        anchors.bottom: parent.bottom
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: Math.max(4, parent.width - 2)
                                        height: Math.max(3, parent.height * modelData.words / pipeline.trendMaxWords)
                                        radius: 2
                                        color: modelData.blocking > 0 ? Theme.danger : Theme.success
                                        opacity: 0.75
                                    }
                                    ToolTip.visible: barHot.containsMouse
                                    ToolTip.text: "第" + modelData.num + "章 · " + modelData.words + "字 · 阻断" + modelData.blocking + " 建议" + modelData.advisory
                                    MouseArea { id: barHot; anchors.fill: parent; hoverEnabled: true }
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
                        onClicked: {
                            pipeline.regenKey = "chapter:" + bridge.lastRecord.num
                            pipeline.regenLabel = "第 " + bridge.lastRecord.num + " 章"
                            regenDialog.open()
                        }
                    }
                    AppButton {
                        text: "打开最新"
                        enabled: bridge.lastRecord.num !== undefined
                        Layout.fillWidth: true
                        onClicked: pipeline.openChapter(bridge.lastRecord.num)
                    }
                }

                Item { height: 8 }
            }
        }
    }

    // ---- 阶段重生成对话框（查看产物 / 带指导重生成）----
    Dialog {
        id: regenDialog
        objectName: "regenDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: pipeline.regenKey.indexOf("chapter:") === 0
                  ? "重写 " + pipeline.regenLabel + "？"
                  : "重生成「" + pipeline.regenLabel + "」？"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                visible: pipeline.regenKey.indexOf("chapter:") !== 0
                width: parent.width
                text: "将删除该阶段产物，点「开始」后从该阶段重新生成。" + (pipeline.regenKey === "outline" ? "\n注意：大纲重生成会连带清除全部细纲。" : "")
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                visible: pipeline.regenKey.indexOf("chapter:") === 0
                width: parent.width
                text: "当前正文将被移除并重新生成。旧内容会先归档为「重写前备份」版本——不满意可在版本历史回退。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                text: "重生成指导（可选，注入生成 prompt）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            TextArea {
                id: regenGuidance
                width: parent.width
                height: 68
                placeholderText: "如：设定里把世界观改得更黑暗；大纲按三幕式重排；本章打脸再狠一点…"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
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
                onClicked: regenDialog.close()
            }
            AppButton {
                text: "确认重生成"
                kind: "primary"
                onClicked: {
                    if (pipeline.regenKey.indexOf("chapter:") === 0)
                        bridge.rewriteChapterWithGuidance(parseInt(pipeline.regenKey.substring(8)), regenGuidance.text)
                    else
                        bridge.regenerateStage(pipeline.regenKey, regenGuidance.text)
                    pipeline.refresh()
                    regenGuidance.text = ""
                    regenDialog.close()
                }
            }
        }
    }
}
