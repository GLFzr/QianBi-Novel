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
    property string activePanel: "shelf"
    property bool logVisible: false
    property bool showReasoning: false   // 思维链默认隐藏，用户主动打开才展示
    property int selStart: -1            // 局部改写：选中区间
    property int selEnd: -1
    property int pendingChapter: -1      // 未保存确认后待执行动作：>=0 打开该章，-2 关闭窗口

    // 未保存保护：切换章节 / 关闭窗口前若有未保存修改 → 弹「保存/放弃/取消」
    function tryOpenChapter(n) {
        if (bridge.editorDirty && !bridge.isStreaming) {
            mainWindow.pendingChapter = n
            unsavedDialog.open()
        } else {
            bridge.openChapter(n)
            editorHolder.ensureChapterVisible()
        }
    }

    // 未保存确认对话框的回调：doSave=true 保存并继续，false 放弃修改
    function afterUnsavedChoice(doSave) {
        if (doSave) bridge.saveChapterText(editor.text)
        else bridge.clearEditorDirty()
        var act = mainWindow.pendingChapter
        mainWindow.pendingChapter = -1
        unsavedDialog.close()
        if (act === -2) mainWindow.close()
        else if (act >= 0) {
            bridge.openChapter(act)
            editorHolder.ensureChapterVisible()
        }
    }

    onClosing: function (close) {
        if (bridge.editorDirty && !bridge.isStreaming) {
            mainWindow.pendingChapter = -2
            unsavedDialog.open()
            close.accepted = false
        }
    }

    // 项目打开后自动进入流水线（用户手动选择的面板保持不动）
    Connections {
        target: bridge
        function onHasProjectChanged() {
            if (bridge.hasProject && mainWindow.activePanel === "shelf")
                mainWindow.activePanel = "pipeline"
        }
    }
    Component.onCompleted: {
        // 兜底：启动时项目可能已加载（信号在 QML 建立前发出）
        if (bridge.hasProject) mainWindow.activePanel = "pipeline"
        // 崩溃/意外退出后的未保存草稿 → 提示恢复（恢复仍是工作副本，保存才成版本）
        if (bridge.hasRecoverableDraft) Qt.callLater(function () { recoverDialog.open() })
        // 窗口位置超出屏幕可视区时重置居中（防窗口被拖出屏幕导致内容"被挡住"）
        Qt.callLater(function () {
            var aw = Screen.desktopAvailableWidth
            var ah = Screen.desktopAvailableHeight
            if (mainWindow.x < -mainWindow.width + 80 || mainWindow.y < -mainWindow.height + 80
                    || mainWindow.x > aw - 80 || mainWindow.y > ah - 80) {
                mainWindow.x = Math.max(0, (aw - mainWindow.width) / 2)
                mainWindow.y = Math.max(0, (ah - mainWindow.height) / 2)
            }
        })
    }

    RowLayout {
        anchors.fill: parent
        anchors.bottomMargin: statusBar.height   // 给底部状态栏让位，避免盖住面板底部按钮
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
                        radius: 10
                        enabled: modelData.key !== "shelf" ? bridge.hasProject : true
                        opacity: enabled ? 1.0 : 0.35
                        color: mainWindow.activePanel === modelData.key ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                             : navHover.containsMouse ? Theme.bgHover : "transparent"
                        // 选中指示条
                        Rectangle {
                            visible: mainWindow.activePanel === modelData.key
                            width: 3; height: 18
                            radius: 2
                            anchors.left: parent.left
                            anchors.leftMargin: 0
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.accent
                        }
                        Text {
                            anchors.centerIn: parent
                            text: modelData.icon
                            color: mainWindow.activePanel === modelData.key ? Theme.accent : Theme.textSecondary
                            font.pixelSize: 16
                            font.bold: mainWindow.activePanel === modelData.key
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
                    onOpenChapter: function (n) { mainWindow.tryOpenChapter(n) }
                }
                ChapterPanel {
                    onOpenChapter: function (n) { mainWindow.tryOpenChapter(n) }
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
                        text: bridge.streamStageLabel !== "" ? "正在" + bridge.streamStageLabel + "…" : "生成中…"
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
                        text: "局部重写"
                        visible: !bridge.isStreaming
                        enabled: !bridge.isStreaming && editor.selectedText !== "" && !bridge.isRewritingSelection
                        onClicked: {
                            mainWindow.selStart = editor.selectionStart
                            mainWindow.selEnd = editor.selectionEnd
                            rewriteDialog.open()
                        }
                    }
                    AppButton {
                        text: bridge.editorDirty ? "● 保存" : "保存"
                        kind: bridge.editorDirty ? "primary" : "ghost"
                        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
                        onClicked: bridge.saveChapterText(editor.text)
                        ToolTip.visible: hovered
                        ToolTip.text: bridge.editorDirty ? "有未保存修改，保存后产生新版本" : "保存正文并生成新版本"
                    }
                    Rectangle {
                        // 未保存标记：黄色圆点（内容有改动即出现）
                        visible: bridge.editorDirty
                        width: 9
                        height: 9
                        radius: 4.5
                        color: "#E8B339"
                        border.width: 1
                        border.color: "#8a6a1c"
                        Layout.alignment: Qt.AlignVCenter
                        MouseArea {
                            id: ma
                            anchors.fill: parent
                            hoverEnabled: true
                            ToolTip.visible: ma.hovered
                            ToolTip.text: "未保存（工作副本）"
                        }
                    }
                    AppButton {
                        text: "版本"
                        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
                        onClicked: {
                            versionListModel.clear()
                            var vs = bridge.versionsForChapter(bridge.currentChapterNum)
                            for (var i = 0; i < vs.length; i++)
                                versionListModel.append(vs[i])
                            versionsDialog.open()
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: "版本历史（保存驱动）：查看 / 对比 / 回退"
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
                    AppButton {
                        visible: bridge.isStreaming
                        text: showReasoning ? "隐藏思考" : "显示思考"
                        kind: "ghost"
                        checkable: false
                        onClicked: showReasoning = !showReasoning
                    }
                }
            }

            // ---- 正文编辑区（主体） ----
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 10
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: Theme.bgHover
                        Behavior on implicitWidth { NumberAnimation { duration: 100 } }
                    }
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
                    // 正文限宽居中（阅读宽度 ~820px，写作工具标准排版）
                    leftPadding: Math.max(56, Math.min(320, (editorHolder.width - 820) / 2))
                    rightPadding: Math.max(56, Math.min(320, (editorHolder.width - 820) / 2))
                    topPadding: 30
                    bottomPadding: 70
                    background: Rectangle { color: Theme.bgPage }

                    // 流式输出时光标跟随末尾；非流式编辑时同步未保存状态（保存驱动）
                    onTextChanged: {
                        if (bridge.isStreaming) {
                            cursorPosition = text.length
                            Qt.callLater(function () {
                                var fl = editor.flickableItem
                                if (fl) fl.positionViewAtEnd()
                            })
                        } else {
                            bridge.markEditorDirty(text)
                        }
                    }
                }
            }

            // ---- 思维链面板（默认隐藏，用户点「显示思考」才展开）----
            Rectangle {
                Layout.fillWidth: true
                visible: mainWindow.showReasoning && bridge.isStreaming && bridge.reasoningText !== ""
                height: 150
                color: Theme.bgLog
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4
                    Text {
                        text: "AI 思考过程（仅你可见）"
                        color: Theme.info
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                        font.bold: true
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TextArea {
                            id: reasoningArea
                            text: bridge.reasoningText
                            readOnly: true
                            color: Theme.textSecondary
                            font.family: Theme.monoFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                            background: Rectangle { color: "transparent" }
                            onTextChanged: {
                                cursorPosition = text.length
                                Qt.callLater(function () {
                                    var fl = reasoningArea.flickableItem
                                    if (fl) fl.positionViewAtEnd()
                                })
                            }
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
        id: statusBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 28
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
                text: "已暂停"
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

    // ---- 局部重写对话框（选中段落 + 想法 → AI 只改这一段）----
    Dialog {
        id: rewriteDialog
        parent: Overlay.overlay
        modal: true
        width: 620
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "局部重写选中段落"
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            // 选中段原文（只读）
            Text {
                text: "选中段落（" + (mainWindow.selEnd - mainWindow.selStart) + " 字符）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Rectangle {
                width: parent.width
                height: 90
                radius: Theme.rBtn
                color: Theme.bgLog
                border.width: 1
                border.color: Theme.border
                clip: true
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        text: editor.selectedText !== "" ? editor.selectedText : ""
                        readOnly: true
                        color: Theme.textSecondary
                        font.family: Theme.serifFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
            }
            // 想法输入
            Text {
                text: "你的修改想法（告诉 AI 想怎么改）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            TextArea {
                id: rewriteIdea
                width: parent.width
                height: 64
                placeholderText: "如：这段打脸写得不够爽，把围观者的反应写出来；或：女主的台词太软，改成直接拒绝…"
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
            // 流式预览
            Text {
                visible: bridge.isRewritingSelection
                text: "AI 改写中（实时预览）…"
                color: Theme.accent
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Rectangle {
                visible: bridge.isRewritingSelection || bridge.selectionDraftText !== ""
                width: parent.width
                height: 130
                radius: Theme.rBtn
                color: Theme.bgLog
                border.width: 1
                border.color: bridge.isRewritingSelection ? Theme.accent : Theme.border
                clip: true
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        text: bridge.selectionDraftText
                        readOnly: true
                        color: Theme.textPrimary
                        font.family: Theme.serifFont
                        font.pixelSize: Theme.fsBody
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                        onTextChanged: {
                            cursorPosition = text.length
                            Qt.callLater(function () {
                                var fl = parent.parent.flickableItem
                                if (fl) fl.positionViewAtEnd()
                            })
                        }
                    }
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "放弃"
                kind: "ghost"
                onClicked: { bridge.cancelSelectionRewrite(); rewriteDialog.close() }
            }
            AppButton {
                text: "开始改写"
                kind: "primary"
                visible: !bridge.isRewritingSelection
                onClicked: {
                    var before = editor.getText(0, mainWindow.selStart)
                    var sel = editor.getText(mainWindow.selStart, mainWindow.selEnd)
                    var after = editor.getText(mainWindow.selEnd, editor.text.length)
                    bridge.rewriteSelection(before, sel, after, rewriteIdea.text)
                }
            }
            AppButton {
                text: "应用改写"
                kind: "primary"
                visible: !bridge.isRewritingSelection && bridge.selectionDraftText !== ""
                onClicked: {
                    var result = bridge.selectionResult()
                    if (result !== "") {
                        bridge.noteEditAction("局部改写")
                        editor.remove(mainWindow.selStart, mainWindow.selEnd)
                        editor.insert(mainWindow.selStart, result)
                        mainWindow.selStart = -1
                        mainWindow.selEnd = -1
                    }
                    bridge.cancelSelectionRewrite()
                    rewriteDialog.close()
                }
            }
        }
        onClosed: {
            bridge.cancelSelectionRewrite()
            rewriteIdea.text = ""
        }
    }

    // ---- 未保存保护：切换章节 / 关闭窗口前的「保存/放弃/取消」----
    Dialog {
        id: unsavedDialog
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "有未保存的修改"
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 8
            width: parent.width
            Text {
                width: parent.width
                text: "当前章节有未保存的修改（工作副本）。版本只在你点「保存」时产生——请选择："
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: "· 保存：提交为新版本后继续\n· 放弃：丢弃本次修改，不产生版本\n· 取消：回到当前内容"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                lineHeight: 1.6
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: { mainWindow.pendingChapter = -1; unsavedDialog.close() }
            }
            AppButton {
                text: "放弃"
                kind: "ghost"
                onClicked: mainWindow.afterUnsavedChoice(false)
            }
            AppButton {
                text: "保存并继续"
                kind: "primary"
                onClicked: mainWindow.afterUnsavedChoice(true)
            }
        }
    }

    // ---- 版本历史（保存驱动）：查看 / 对比 / 回退 ----
    Dialog {
        id: versionsDialog
        parent: Overlay.overlay
        modal: true
        width: 820
        height: 540
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(24, Math.round((parent.height - height) / 2)) : 0
        padding: 0
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Column {
            padding: 16
            spacing: 2
            Text {
                text: "版本历史 · 第 " + bridge.currentChapterNum + " 章（保存驱动：仅「保存」产生版本）"
                color: Theme.textPrimary
                font.family: Theme.serifFont
                font.pixelSize: Theme.fsTitle
                font.bold: true
            }
            Text {
                text: "版本内容 vs 当前已保存内容：红=已移除 · 绿=新增 · 回退只进工作副本，保存后才提交"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
            }
        }
        property int selVersion: -1
        contentItem: RowLayout {
            spacing: 0
            anchors.fill: parent
            // 左：版本列表
            Rectangle {
                Layout.preferredWidth: 250
                Layout.fillHeight: true
                color: Theme.bgPanel
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 4
                    ListView {
                        id: versionList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: ListModel { id: versionListModel }
                        delegate: Rectangle {
                            width: ListView.view.width
                            height: 64
                            radius: Theme.rBtn
                            color: versionList.currentIndex === index ? Theme.bgHover : "transparent"
                            border.width: versionList.currentIndex === index ? 1 : 0
                            border.color: Theme.accent
                            Column {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 2
                                Row {
                                    spacing: 6
                                    Text {
                                        text: "v" + model.v
                                        color: Theme.accent
                                        font.family: Theme.monoFont
                                        font.pixelSize: Theme.fsBody
                                        font.bold: true
                                    }
                                    Text {
                                        text: model.source
                                        color: Theme.info
                                        font.family: Theme.uiFont
                                        font.pixelSize: Theme.fsTiny
                                    }
                                }
                                Text {
                                    text: model.ts + "  ·  " + model.words + " 字"
                                    color: Theme.textTertiary
                                    font.family: Theme.monoFont
                                    font.pixelSize: Theme.fsTiny
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    versionList.currentIndex = index
                                    versionsDialog.selVersion = model.v
                                }
                            }
                        }
                    }
                    Text {
                        visible: versionListModel.count === 0
                        Layout.fillWidth: true
                        text: "本章还没有版本。\n点击「保存」会归档旧内容为新版本。"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                        wrapMode: Text.Wrap
                    }
                }
            }
            // 右：diff 对比（选中版本 vs 当前已保存）
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                anchors.margins: 10
                spacing: 6
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.rBtn
                    color: Theme.bgLog
                    border.width: 1
                    border.color: Theme.border
                    clip: true
                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 6
                        ListView {
                            id: diffList
                            model: ListModel { id: diffListModel }
                            clip: true
                            delegate: Text {
                                width: diffList.width
                                text: model.text
                                color: model.op === "del" ? "#E06C6C"
                                     : model.op === "add" ? "#7BC47F" : Theme.textSecondary
                                font.family: Theme.monoFont
                                font.pixelSize: Theme.fsTiny
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: diffListModel.count === 0
                        text: "← 选择一个版本查看与当前已保存内容的差异\n（红=已移除 · 绿=新增）"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                    }
                }
                Row {
                    spacing: 8
                    Layout.alignment: Qt.AlignRight
                    AppButton {
                        text: "关闭"
                        kind: "ghost"
                        onClicked: versionsDialog.close()
                    }
                    AppButton {
                        text: "回退到工作副本"
                        kind: "primary"
                        enabled: versionsDialog.selVersion > 0
                        onClicked: {
                            // 回退 = 版本内容进工作副本（不落盘），保存才提交为新版本
                            var t = bridge.readVersion(bridge.currentChapterNum, versionsDialog.selVersion)
                            if (t !== "") {
                                bridge.noteEditAction("整章重写")
                                editor.text = t
                                versionsDialog.close()
                                bridge.showToast("ok", "已回退到 v" + versionsDialog.selVersion
                                                 + "（工作副本未保存），点「保存」提交为新版本")
                            }
                        }
                    }
                }
            }
        }
        onOpened: {
            versionsDialog.selVersion = -1
            diffListModel.clear()
            if (versionListModel.count > 0) {
                versionList.currentIndex = 0
                versionsDialog.selVersion = versionListModel.get(0).v
            }
        }
        onSelVersionChanged: {
            if (versionsDialog.selVersion > 0) {
                diffListModel.clear()
                var ds = bridge.diffVersionWithDisk(bridge.currentChapterNum, versionsDialog.selVersion)
                for (var i = 0; i < ds.length; i++)
                    diffListModel.append(ds[i])
            }
        }
    }

    // ---- 崩溃/意外退出后的未保存草稿恢复 ----
    Dialog {
        id: recoverDialog
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "发现未保存草稿"
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 8
            width: parent.width
            Text {
                width: parent.width
                text: "上次退出时检测到未保存的修改（已自动暂存，未产生任何版本）。要恢复吗？"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: "恢复后仍只是工作副本——点「保存」才会提交为新版本。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "丢弃草稿"
                kind: "ghost"
                onClicked: { bridge.discardDrafts(); recoverDialog.close() }
            }
            AppButton {
                text: "恢复草稿"
                kind: "primary"
                onClicked: {
                    var r = bridge.recoverDraft()
                    if (r && r.text !== undefined && r.num !== undefined) {
                        editor.text = r.text   // 触发 markEditorDirty → 未保存标记亮起
                        editorHolder.ensureChapterVisible()
                    }
                    recoverDialog.close()
                }
            }
        }
    }
}
