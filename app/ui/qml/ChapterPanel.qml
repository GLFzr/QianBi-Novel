import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// 章节面板：章节列表（阅读/重写/带指导重写）+ 项目文件入口
Item {
    id: chapterPanel

    signal openChapter(int num)
    signal showNeedsFix()

    property int guidanceNum: 0
    property int confirmNum: 0

    // 驾驶舱「查看」入口：直接打开指定项目文件（设定/大纲）
    function openProjectFile(rel) {
        if (rel === "") return
        fileDialog.currentRel = rel
        fileEditor.text = bridge.readProjectFile(rel)
        fileDialog.open()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            height: 66
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                Column {
                    spacing: 3
                    Text {
                        text: "章节"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTitle
                        font.bold: true
                    }
                    Text {
                        text: bridge.progressText
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.monoFont
                    }
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    visible: bridge.needsFixCount > 0
                    text: "待修 " + bridge.needsFixCount
                    kind: "danger"
                    height: 28
                    ToolTip.visible: hovered
                    ToolTip.text: "审校检出阻塞问题的章节，点击查看汇总并一键修复"
                    ToolTip.delay: 400
                    onClicked: chapterPanel.showNeedsFix()
                }
                AppButton {
                    text: "项目文件"
                    height: 28
                    onClicked: {
                        fileModel.clear()
                        var files = bridge.projectFiles()
                        for (var i = 0; i < files.length; i++) fileModel.append(files[i])
                        fileDialog.open()
                    }
                }
            }
        }

        // 章节列表
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: bridge.chapterModelProp
            spacing: 3
            clip: true
            anchors.margins: 10

            delegate: QueueRow {
                width: ListView.view.width - 20
                num: model.num
                title: model.title
                state: model.state
                words: model.words
                note: model.note
                onOpenChapter: function (n) { chapterPanel.openChapter(n) }
                onRewriteChapter: function (n) {
                    // 重写确认：旧正文先归档为「重写前备份」版本，放弃时可回退
                    chapterPanel.confirmNum = n
                    rewriteConfirmDialog.open()
                }
                onRequestGuidanceRewrite: function (n) {
                    chapterPanel.guidanceNum = n
                    chapterGuidanceDialog.open()
                }
                onViewIssues: function (n) { bridge.showReviewIssues(n) }
                onViewGenConfig: function (n) { bridge.showGenConfig(n) }
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
            visible: bridge.chapterModelProp.rowCount === 0
            Text {
                text: "还没有章节\n点「流水线 开始」启动写作"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    // ---- 带指导重写对话框（面板级统一，窗口居中）----
    Dialog {
        id: chapterGuidanceDialog
        objectName: "chapterGuidanceDialog"
        parent: Overlay.overlay
        modal: true
        width: 440
        padding: 18
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        background: DialogBg {}
        header: Text {
            text: "带指导重写 第 " + chapterPanel.guidanceNum + " 章"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 18
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                text: "写下你对本章的重写要求（会注入正文生成 prompt）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                wrapMode: Text.Wrap
                width: parent.width
            }
            TextArea {
                id: guidanceArea
                width: parent.width
                height: 96
                placeholderText: "如：这章别写死女主；打脸要写在场配角的反应；结尾钩子指向下章的拍卖会…"
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
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: chapterGuidanceDialog.close()
            }
            AppButton {
                text: "重写"
                kind: "primary"
                onClicked: {
                    bridge.rewriteChapterWithGuidance(chapterPanel.guidanceNum, guidanceArea.text)
                    guidanceArea.text = ""
                    chapterGuidanceDialog.close()
                }
            }
        }
    }

    // ---- 项目文件浏览/编辑对话框 ----
    Dialog {
        id: fileDialog
        objectName: "fileDialog"
        parent: Overlay.overlay
        modal: true
        width: 820
        height: 540
        padding: 0
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
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
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }

        ListModel { id: fileModel }

        contentItem: RowLayout {
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 220
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
                        height: 32
                        radius: 6
                        color: fileList.currentIndex === index ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12) : "transparent"
                        RowLayout {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            spacing: 6
                            Text {
                                Layout.fillWidth: true
                                text: model.dir
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                                elide: Text.ElideLeft
                            }
                            Text {
                                Layout.preferredWidth: 130
                                text: model.name
                                color: fileList.currentIndex === index ? Theme.accent : Theme.textPrimary
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.uiFont
                                elide: Text.ElideRight
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
                    // 空态：未从「项目文件」入口加载时的兜底说明
                    AppEmptyState {
                        anchors.centerIn: parent
                        visible: fileModel.count === 0
                        iconName: "doc"
                        title: "没有可列出的项目文件"
                        hint: "「项目文件」入口自动加载产物"
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 10
                spacing: 6
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
                        font.family: Theme.uiFont
                        font.pixelSize: 15
                        wrapMode: Text.Wrap
                        selectByMouse: true
                        background: Rectangle { color: Theme.bgLog; radius: 8 }
                        padding: 10
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

    // ---- 整章重写确认（保存驱动语义：旧正文先归档「重写前备份」版本）----
    Dialog {
        id: rewriteConfirmDialog
        objectName: "rewriteConfirmDialog"
        parent: Overlay.overlay
        modal: true
        width: 460
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "重写第 " + chapterPanel.confirmNum + " 章？"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 8
            width: parent.width
            Text {
                width: parent.width
                text: "当前正文将被移除并重新生成。旧内容会先归档为「重写前备份」版本——重写后不满意，可在「版本历史」中回退（回退只进工作副本，保存才提交）。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: rewriteConfirmDialog.close()
            }
            AppButton {
                text: "确认重写"
                kind: "primary"
                onClicked: { bridge.rewriteChapter(chapterPanel.confirmNum); rewriteConfirmDialog.close() }
            }
        }
    }
}
