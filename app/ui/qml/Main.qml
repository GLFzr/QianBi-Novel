import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 千笔一文 Novel — 写作工作台
// 布局：左=功能图标栏 | 次左=功能面板 | 中央=小说正文大编辑器（常驻主体）
// 中央编辑器始终可见：写作时流式输出（只读），定稿后解锁编辑
// ============================================================
ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1400
    height: 900
    minimumWidth: 1080
    minimumHeight: 700
    title: "千笔一文 Novel"
    color: Theme.bgPage

    readonly property var navItems: [
        { "label": "书架", "icon": "▤", "key": "shelf" },
        { "label": "流水线", "icon": "▶", "key": "pipeline" },
        { "label": "章节", "icon": "☰", "key": "chapters" },
        { "label": "设置", "icon": "⚙", "key": "settings" }
    ]
    property string activePanel: bridge.hasProject ? "pipeline" : "shelf"
    property bool logVisible: false

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ========== 最左：功能图标栏 ==========
        Rectangle {
            Layout.preferredWidth: 52
            Layout.fillHeight: true
            color: Theme.bgPanel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 10
                anchors.bottomMargin: 10
                spacing: 4

                // Logo
                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    width: 32; height: 32; radius: 8
                    color: Theme.accent
                    Text {
                        anchors.centerIn: parent
                        text: "文"
                        color: "#1D1B17"
                        font.family: Theme.serifFont
                        font.pixelSize: 15
                        font.bold: true
                    }
                }
                Item { Layout.fillWidth: true; height: 6 }

                // 功能图标
                Repeater {
                    model: mainWindow.navItems
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        Layout.alignment: Qt.AlignHCenter
                        width: 38; height: 38
                        radius: 9
                        enabled: modelData.key !== "shelf" ? bridge.hasProject : true
                        opacity: enabled ? 1.0 : 0.35
                        color: mainWindow.activePanel === modelData.key ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                             : navHover.containsMouse ? Theme.bgHover : "transparent"
                        Text {
                            anchors.centerIn: parent
                            text: modelData.icon
                            color: mainWindow.activePanel === modelData.key ? Theme.accent : Theme.textSecondary
                            font.pixelSize: 16
                        }
                        MouseArea {
                            id: navHover
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            enabled: parent.enabled
                            onClicked: mainWindow.activePanel = modelData.key
                        }
                        ToolTip.visible: navHover.containsMouse
                        ToolTip.text: modelData.label
                    }
                }

                Item { Layout.fillHeight: true }

                // 日志开关
                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    width: 38; height: 38
                    radius: 9
                    color: mainWindow.logVisible ? Qt.rgba(Theme.info.r, Theme.info.g, Theme.info.b, 0.16)
                         : logHover.containsMouse ? Theme.bgHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "≡"
                        color: mainWindow.logVisible ? Theme.info : Theme.textSecondary
                        font.pixelSize: 16
                    }
                    MouseArea {
                        id: logHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: mainWindow.logVisible = !mainWindow.logVisible
                    }
                    ToolTip.visible: logHover.containsMouse
                    ToolTip.text: "运行日志"
                }
            }
        }

        // ========== 次左：功能面板 ==========
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: Theme.bgPanel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            StackLayout {
                id: panelStack
                objectName: "panelStack"
                anchors.fill: parent
                currentIndex: mainWindow.activePanel === "shelf" ? 0
                             : mainWindow.activePanel === "pipeline" ? 1
                             : mainWindow.activePanel === "chapters" ? 2 : 3

                BookshelfPanel {}
                PipelinePanel {
                    onOpenChapter: function (n) { bridge.openChapter(n); editorHolder.ensureChapterVisible() }
                }
                ChapterPanel {
                    onOpenChapter: function (n) { bridge.openChapter(n); editorHolder.ensureChapterVisible() }
                }
                SettingsPanel {}
            }
        }

        // ========== 中央：小说正文编辑器（常驻主体） ==========
        ColumnLayout {
            id: editorHolder
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            function ensureChapterVisible() {
                // 章节切换后确保编辑区获得焦点（面板回调）
                editor.forceActiveFocus()
            }

            // ---- 编辑器顶栏 ----
            Rectangle {
                Layout.fillWidth: true
                height: 52
                color: Theme.bgPanel
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 18
                    anchors.rightMargin: 14
                    spacing: 12

                    Column {
                        spacing: 1
                        Text {
                            text: bridge.chapterPath
                                  ? bridge.chapterPath.split(/[\\/]/).pop().replace(".md", "")
                                  : (bridge.isStreaming ? "正在写作…" : "未打开章节")
                            color: Theme.textPrimary
                            font.family: Theme.serifFont
                            font.pixelSize: Theme.fsTitle
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            text: bridge.bookTitle + (bridge.bookMeta ? " · " + bridge.bookMeta : "")
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                        }
                    }
                    Item { Layout.fillWidth: true }

                    Text {
                        visible: editor.text !== ""
                        text: "字数：" + editor.text.replace(/\s/g, "").length
                        color: Theme.textTertiary
                        font.family: Theme.monoFont
                        font.pixelSize: Theme.fsTiny
                    }
                    Text {
                        visible: bridge.isStreaming
                        text: "⏳ 生成中…"
                        color: Theme.accent
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                    }
                    AppButton {
                        text: "扫描 AI 味"
                        enabled: !bridge.isStreaming && editor.text !== ""
                        onClicked: bridge.scanChapterText(editor.text)
                    }
                    AppButton {
                        text: "💾 保存"
                        kind: "primary"
                        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
                        onClicked: bridge.saveChapterText(editor.text)
                    }
                    AppButton {
                        text: "导出…"
                        enabled: bridge.hasProject && !bridge.isStreaming
                        onClicked: exportMenu.popup()
                        Menu {
                            id: exportMenu
                            palette.window: Theme.bgCard
                            palette.text: Theme.textPrimary
                            MenuItem {
                                text: "导出 txt（平台上传标准）"
                                onTriggered: bridge.exportProject("txt")
                            }
                            MenuItem {
                                text: "导出 epub（阅读器通用）"
                                onTriggered: bridge.exportProject("epub")
                            }
                        }
                    }
                }
            }

            // ---- 正文编辑区（主体） ----
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 5; radius: 2; color: Theme.bgHover }
                    background: Item {}
                }

                TextArea {
                    id: editor
                    text: bridge.isStreaming ? bridge.liveDraftText : bridge.chapterText
                    readOnly: bridge.isStreaming
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: 17
                    wrapMode: Text.Wrap
                    selectByMouse: true
                    persistentSelection: true
                    selectionColor: Theme.accent
                    selectedTextColor: "#1D1B17"
                    leftPadding: 44
                    rightPadding: 44
                    topPadding: 28
                    bottomPadding: 60
                    background: Rectangle { color: Theme.bgPage }

                    // 流式输出时光标跟随末尾
                    onTextChanged: {
                        if (bridge.isStreaming) {
                            cursorPosition = text.length
                            Qt.callLater(function () { positionViewAtEnd() })
                        }
                    }
                }
            }

            // ---- 扫描结果条（底部横条，不占主体） ----
            Rectangle {
                Layout.fillWidth: true
                visible: bridge.chapterFindings.length > 0
                height: 34
                color: Theme.bgPanel
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 6
                    Text {
                        text: "AI 味 " + bridge.chapterFindings.length + " 处"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        orientation: ListView.Horizontal
                        spacing: 6
                        clip: true
                        model: bridge.chapterFindings
                        delegate: Rectangle {
                            height: 22
                            radius: 11
                            color: Theme.bgHover
                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 5
                                Rectangle {
                                    width: 7; height: 7; radius: 4
                                    color: modelData.level === "blocking" ? Theme.danger : Theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.message
                                    color: modelData.level === "blocking" ? Theme.danger : Theme.textPrimary
                                    font.pixelSize: Theme.fsTiny
                                    font.family: Theme.uiFont
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    editor.select(modelData.start, modelData.end)
                                    editor.forceActiveFocus()
                                }
                            }
                            ToolTip.visible: containsMouse && modelData.hint !== ""
                            ToolTip.text: modelData.hint
                        }
                    }
                    AppButton {
                        text: "×"
                        kind: "ghost"
                        height: 22
                        onClicked: bridge.scanChapterText("")
                    }
                }
            }

            // ---- 底部日志（可折叠） ----
            Rectangle {
                Layout.fillWidth: true
                visible: mainWindow.logVisible
                height: 190
                color: Theme.bgLog
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "运行日志"
                            color: Theme.textSecondary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }
                        Item { Layout.fillWidth: true }
                        AppButton {
                            text: "清空"
                            kind: "ghost"
                            height: 20
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
    }

    // ---- 底部状态栏 ----
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 26
        color: Theme.bgPanel
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
        z: 10

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 14
            Text {
                text: bridge.progressText !== "" ? "进度 " + bridge.progressText : "未打开项目"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.monoFont
            }
            Text {
                text: bridge.slotsText
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                elide: Text.ElideRight
                Layout.maximumWidth: 420
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "累计 " + bridge.totalTokens.toLocaleString() + " tokens · ≈ " + bridge.estCost
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.monoFont
            }
            Text {
                visible: bridge.isPaused
                text: "⏸ 已暂停"
                color: Theme.accent
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
        }
    }

    // ---- 全局 Toast ----
    Rectangle {
        id: toastBar
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 36
        width: Math.min(560, toastText.implicitWidth + 48)
        height: 40
        radius: 20
        color: Theme.bgHover
        border.width: 1
        border.color: toastBar.toastLevel === "error" ? Theme.danger
                 : toastBar.toastLevel === "warn" ? Theme.accent
                 : Theme.borderStrong
        opacity: 0
        visible: opacity > 0
        z: 100

        property string toastLevel: "info"

        function showToast(level, msg) {
            toastBar.toastLevel = level
            toastText.text = msg
            toastAnim.restart()
        }

        Text {
            id: toastText
            anchors.centerIn: parent
            color: Theme.levelColor(toastBar.toastLevel)
            font.pixelSize: Theme.fsSmall
            font.family: Theme.uiFont
            width: Math.min(520, implicitWidth)
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }

        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toastBar; property: "opacity"; to: 1; duration: 160 }
            PauseAnimation { duration: 2600 }
            NumberAnimation { target: toastBar; property: "opacity"; to: 0; duration: 300 }
        }
    }

    Connections {
        target: bridge
        function onToast(level, msg) { toastBar.showToast(level, msg) }
        function onProjectOpened() {
            mainWindow.activePanel = "pipeline"
            // 自动打开最新章节
            var chs = bridge.chapterModelProp.rowCount
            if (bridge.lastRecord.num !== undefined) bridge.openChapter(bridge.lastRecord.num)
        }
    }
}
