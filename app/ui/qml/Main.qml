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

    // v0.13 主题切换：从 C++ 端 cfg.ui_theme 读取，同步到 Theme 单例
    Connections {
        target: bridge
        function onThemeChanged() {
            Theme.setActive(bridge.currentTheme())
        }
    }

    readonly property var navItems: [
        { "label": "书架", "icon": "shelf", "key": "shelf" },
        { "label": "流水线", "icon": "play", "key": "pipeline" },
        { "label": "章节", "icon": "chapters", "key": "chapters" },
        { "label": "契约", "icon": "contract", "key": "contract" },
        { "label": "笔记", "icon": "notes", "key": "notes" },
        { "label": "预设库", "icon": "library", "key": "library" },
        { "label": "设置", "icon": "settings", "key": "settings" }
    ]
    property string activePanel: "shelf"
    property bool logVisible: false
    property int selStart: -1            // 局部改写：选中区间
    property int selEnd: -1
    property int pendingChapter: -1      // 未保存确认后待执行动作：>=0 打开该章，-2 关闭窗口
    property string rewriteCtxMode: "neighbor"   // 改写上下文：only/neighbor/full/setting
    property var edPrefs: ({ fontScale: 1.0, narrow: true, streamSmooth: false })
    // 流式速度：即时全文 vs 打字机平滑（S4）——打字机用 33ms 节流渲染增量
    property string streamFull: ""
    property string streamShown: ""
    Timer {
        id: typewriter
        interval: 33
        running: bridge.isStreaming && mainWindow.edPrefs.streamSmooth
                 && mainWindow.streamShown.length < mainWindow.streamFull.length
        onTriggered: {
            var full = mainWindow.streamFull
            var shown = mainWindow.streamShown
            // 追帧：每 tick 补 1/6 缺口（既平滑又不落后太多）
            var n = Math.min(full.length, shown.length + Math.max(2, Math.ceil((full.length - shown.length) / 6)))
            mainWindow.streamShown = full.substring(0, n)
        }
    }

    // 面板序号由 navItems 推导：加一块面板不会再出现「索引和 key 对不上」
    function panelIndexOf(key) {
        for (var i = 0; i < navItems.length; i++)
            if (navItems[i].key === key) return i
        return 0
    }

    // 进入沉浸阅读：当前章含未保存工作副本时把编辑器内容一并带入（未定稿徽章）
    function openReader() {
        if (!bridge.hasProject) { bridge.showToast("warn", "请先打开项目"); return }
        var num = bridge.currentChapterNum
        if (num > 0 && bridge.editorDirty) readerView.open(num, editor.text)
        else {
            var chs = bridge.readerChapterList()
            if (chs.length === 0) { bridge.showToast("warn", "还没有可读的章节"); return }
            readerView.open(num > 0 ? num : chs[chs.length - 1].num, "")
        }
    }

    // 统一保存入口：共写档=产物保存（不走版本快照）；自动档=正文保存（保存驱动版本）
    function saveEditor() {
        if (bridge.cwMode === "cw") bridge.saveCwProduct(editor.text)
        else bridge.saveChapterText(editor.text)
    }

    // ---- 全局快捷键 ----
    Shortcut {
        sequence: StandardKey.Save
        enabled: bridge.editorDirty && !bridge.isStreaming && bridge.canSaveEditor
                 && !(bridge.cwMode === "cw" && bridge.chapterLocked)
        onActivated: mainWindow.saveEditor()
    }
    Shortcut {
        sequence: "F5"
        enabled: !readerView.visible
        onActivated: mainWindow.openReader()
    }
    Shortcut {
        sequence: "Escape"
        enabled: readerView.visible
        onActivated: readerView.close()
    }
    Shortcut {
        sequence: "Left"
        enabled: readerView.visible
        onActivated: readerView.pageStep(-1)
    }
    Shortcut {
        sequence: "Right"
        enabled: readerView.visible
        onActivated: readerView.pageStep(1)
    }
    Shortcut {
        sequence: "Ctrl+B"
        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
        onActivated: versionsBtn.clicked()
    }
    Shortcut {
        sequence: "Ctrl+E"
        enabled: !bridge.isStreaming && editor.selectedText !== "" && !bridge.isRewritingSelection
        onActivated: {
            mainWindow.selStart = editor.selectionStart
            mainWindow.selEnd = editor.selectionEnd
            rewriteDialog.open()
        }
    }

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
        if (doSave) mainWindow.saveEditor()
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
        // v0.13 主题同步：先于其他设置，让 Theme 单例就位
        Theme.setActive(bridge.currentTheme())
        // 编辑器偏好（字号/限宽/流式速度，设置-外观 可调）
        edPrefs = bridge.editorPrefs()
        // 兜底：启动时项目可能已加载（信号在 QML 建立前发出）
        if (bridge.hasProject) mainWindow.activePanel = "pipeline"
        // 崩溃/意外退出后的未保存草稿 → 提示恢复（恢复仍是工作副本，保存才成版本）
        if (bridge.hasRecoverableDraft) Qt.callLater(function () { recoverDialog.open() })
        // 首启向导（T3.5）：未完成过引导 → 自动弹出
        if (!bridge.onboarded) Qt.callLater(function () { wizardDialog.open() })
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

        // ========== 最左：功能图标栏（ZCode 式 48px 纯图标栏）==========
        Rectangle {
            Layout.preferredWidth: 48
            Layout.fillHeight: true
            color: Theme.bgPanel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 8
                anchors.bottomMargin: 8
                spacing: 2

                // Logo · 极简方标
                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    width: 28; height: 28; radius: 6
                    color: Theme.textPrimary
                    Text {
                        anchors.centerIn: parent
                        text: "文"
                        color: Theme.bgPanel
                        font.family: Theme.uiFont
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
                Item { Layout.fillWidth: true; height: 10 }

                // 功能图标（线性图标 + 圆角活动块，无指示条）
                Repeater {
                    model: mainWindow.navItems
                    delegate: Item {
                        required property var modelData
                        required property int index
                        Layout.alignment: Qt.AlignHCenter
                        width: 36; height: 36
                        enabled: modelData.key !== "shelf" ? bridge.hasProject : true
                        opacity: enabled ? 1.0 : 0.3

                        Rectangle {
                            anchors.fill: parent
                            radius: 8
                            color: mainWindow.activePanel === modelData.key ? Theme.bgActive
                                 : navHover.containsMouse ? Theme.bgHover : "transparent"
                            Behavior on color { ColorAnimation { duration: 100 } }
                        }
                        AppIcon {
                            anchors.centerIn: parent
                            name: modelData.icon
                            size: 19
                            color: mainWindow.activePanel === modelData.key ? Theme.textPrimary : Theme.textSecondary
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
                Item {
                    Layout.alignment: Qt.AlignHCenter
                    width: 36; height: 36
                    Rectangle {
                        anchors.fill: parent
                        radius: 8
                        color: mainWindow.logVisible ? Theme.bgActive
                             : logHover.containsMouse ? Theme.bgHover : "transparent"
                        Behavior on color { ColorAnimation { duration: 100 } }
                    }
                    AppIcon {
                        anchors.centerIn: parent
                        name: "log"
                        size: 18
                        color: mainWindow.logVisible ? Theme.textPrimary : Theme.textSecondary
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

        // ========== Agent Console（T4.3：思考链留存 + 对话区，折叠 24px / 展开 280px）==========
        ConsoleDock {
            id: consoleDock
            objectName: "consoleDockItem"
        }

        // ========== 次左：功能面板 ==========
        Rectangle {
            objectName: "funcPanel"
            Layout.preferredWidth: 420
            Layout.fillHeight: true
            color: Theme.bgPanel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

                StackLayout {
                id: panelStack
                objectName: "panelStack"
                anchors.fill: parent
                currentIndex: mainWindow.panelIndexOf(mainWindow.activePanel)

                BookshelfPanel {}
                PipelinePanel {
                    onOpenChapter: function (n) { mainWindow.tryOpenChapter(n) }
                    onOpenProjectFile: function (rel) {
                        mainWindow.activePanel = "chapters"
                        chapterPanelProxy.openProjectFile(rel)
                    }
                }
                ChapterPanel {
                    id: chapterPanelProxy
                    onOpenChapter: function (n) { mainWindow.tryOpenChapter(n) }
                    onShowNeedsFix: {
                        needsFixDialog.refresh()
                        needsFixDialog.open()
                    }
                }
                ContractPanel {
                    onOpenProjectFile: function (rel) { chapterPanelProxy.openProjectFile(rel) }
                }
                NotesPanel {}
                PresetLibraryPanel {}
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

            // ---- 编辑器顶栏（44px · 面包屑标题）----
            Rectangle {
                Layout.fillWidth: true
                height: 44
                color: Theme.bgPanel
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 10
                    spacing: 6

                    Column {
                        spacing: 0
                        Text {
                            text: bridge.chapterTitle
                                  ? bridge.chapterTitle
                                  : (bridge.isStreaming ? "正在写作…" : "未打开章节")
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: bridge.bookTitle !== ""
                            text: bridge.bookTitle + (bridge.bookMeta ? " · " + bridge.bookMeta : "")
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            elide: Text.ElideRight
                        }
                    }
                    Item { Layout.fillWidth: true }

                    Rectangle { visible: editor.text !== ""; width: 1; height: 16; color: Theme.border }
                    Text {
                        visible: editor.text !== ""
                        text: editor.text.replace(/\s/g, "").length + " 字"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                    }
                    Row {
                        visible: bridge.isStreaming
                        spacing: 4
                        Layout.alignment: Qt.AlignVCenter
                        // S2 thinking 呼吸动画：思考期（本轮还没吐正文）三点呼吸，不空白
                        // 判据用 reasoningLive，不能用 reasoningText 非空——后者跨阶段累积
                        Text {
                            visible: bridge.reasoningLive
                            text: "● ● ●"
                            color: Theme.info
                            font.pixelSize: 8
                            anchors.verticalCenter: parent.verticalCenter
                            SequentialAnimation on opacity {
                                running: visible; loops: Animation.Infinite
                                NumberAnimation { to: 0.15; duration: 600 }
                                NumberAnimation { to: 1; duration: 600 }
                            }
                        }
                        Text {
                            text: bridge.reasoningLive
                                  ? "思考中"
                                  : (bridge.streamStageLabel !== "" ? "正在" + bridge.streamStageLabel + "…" : "生成中…")
                            color: bridge.reasoningLive ? Theme.info : Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    AppButton {
                        iconName: "reader"
                        text: "阅读"
                        enabled: bridge.hasProject
                        onClicked: mainWindow.openReader()
                        ToolTip.visible: hovered
                        ToolTip.text: "沉浸阅读模式（像读小说一样读自己的稿子）· 三主题/标注/书签"
                    }
                    AppButton {
                        iconName: "scan"
                        text: ""
                        enabled: !bridge.isStreaming && editor.text !== ""
                        onClicked: bridge.scanChapterText(editor.text)
                        ToolTip.visible: hovered
                        ToolTip.text: "扫描 AI 味"
                    }
                    AppButton {
                        iconName: "pen"
                        text: ""
                        visible: !bridge.isStreaming
                        enabled: !bridge.isStreaming && editor.selectedText !== "" && !bridge.isRewritingSelection
                        onClicked: {
                            mainWindow.selStart = editor.selectionStart
                            mainWindow.selEnd = editor.selectionEnd
                            rewriteDialog.open()
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: "局部改写选中段落 · Ctrl+E"
                    }
                    AppButton {
                        iconName: "save"
                        text: bridge.editorDirty ? "● 保存" : "保存"
                        kind: bridge.editorDirty ? "primary" : "ghost"
                        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
                                 && !(bridge.cwMode === "cw" && bridge.chapterLocked)
                        onClicked: mainWindow.saveEditor()
                        ToolTip.visible: hovered
                        ToolTip.text: bridge.editorDirty ? "有未保存修改，保存后产生新版本" : "保存正文并生成新版本"
                    }
                    // 终稿锁定徽章 + 解锁（M4：章节确定=锁定；显式解锁唯一放行通道）
                    Rectangle {
                        visible: bridge.cwMode === "cw" && bridge.chapterLocked
                        height: 22
                        radius: 11
                        color: Qt.rgba(Theme.success.r, Theme.success.g, Theme.success.b, 0.15)
                        border.width: 1
                        border.color: Theme.success
                        Layout.alignment: Qt.AlignVCenter
                        Text {
                            anchors.centerIn: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            text: "✓ 已确定（终稿锁定）"
                            color: Theme.success
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                    }
                    AppButton {
                        visible: bridge.cwMode === "cw" && bridge.chapterLocked
                        text: "解锁"
                        kind: "ghost"
                        height: 26
                        onClicked: bridge.unlockChapter()
                        ToolTip.visible: hovered
                        ToolTip.text: "显式解锁唯一放行通道；解锁前终稿仍留版本历史"
                    }
                    AppButton {
                        visible: bridge.cwMode === "cw" && bridge.cwStageKey === "cw_prose"
                                 && !bridge.chapterLocked
                        text: "读一遍"
                        kind: "ghost"
                        height: 26
                        onClicked: bridge.readbackChapter()
                        ToolTip.visible: hovered
                        ToolTip.text: "读改揣摩：Agent 通读本章改动、揣摩你的修改意图（review 槽）"
                    }
                    Rectangle {
                        // 未保存标记：黄色圆点（内容有改动即出现）
                        visible: bridge.editorDirty
                        width: 9
                        height: 9
                        radius: 4.5
                        color: "#E5B84E"
                        border.width: 1
                        border.color: "#6E5620"
                        Layout.alignment: Qt.AlignVCenter
                        MouseArea {
                            id: ma
                            anchors.fill: parent
                            hoverEnabled: true
                            ToolTip.visible: ma.hovered === true
                            ToolTip.text: "未保存（工作副本）"
                        }
                    }
                    AppButton {
                        id: versionsBtn
                        iconName: "history"
                        text: ""
                        enabled: !bridge.isStreaming && bridge.chapterPath !== ""
                        onClicked: {
                            versionListModel.clear()
                            var vs = bridge.versionsForChapter(bridge.currentChapterNum)
                            for (var i = 0; i < vs.length; i++)
                                versionListModel.append(vs[i])
                            versionsDialog.open()
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: "版本历史（保存驱动）：查看 / 对比 / 回退 · Ctrl+B"
                    }
                    AppButton {
                        iconName: "export"
                        text: ""
                        enabled: bridge.hasProject && !bridge.isStreaming
                        onClicked: {
                            exportDialog.refreshPreview()
                            exportDialog.open()
                        }
                    }
                    AppButton {
                        text: bridge.showReasoning ? "隐藏思考" : "显示思考"
                        kind: "ghost"
                        checkable: false
                        onClicked: bridge.setShowReasoning(!bridge.showReasoning)
                    }
                }
            }

            // ---- 共写档阶段导航（六卡；自动档不占位）----
            Rectangle {
                Layout.fillWidth: true
                visible: bridge.cwMode === "cw"
                height: 36
                color: Theme.bgPanel
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                StageStepperCW {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    anchors.topMargin: 3
                    anchors.bottomMargin: 3
                }
            }

            // ---- 主编辑列（M1）：共写档 = 对话区 + 编辑器并排；自动档 = 纯编辑区 ----
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                CwDialogueDock {
                    id: cwDock
                    Layout.preferredWidth: 480
                    Layout.fillHeight: true
                    Layout.maximumWidth: 560
                    visible: bridge.cwMode === "cw"
                }
                Rectangle {
                    visible: bridge.cwMode === "cw"
                    Layout.fillHeight: true
                    width: 1
                    color: Theme.border
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
                    text: bridge.isStreaming ? (mainWindow.edPrefs.streamSmooth ? mainWindow.streamShown : bridge.liveDraftText) : bridge.chapterText
                    readOnly: bridge.isStreaming || (bridge.cwMode === "cw" && bridge.chapterLocked)
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: Math.round(17 * (mainWindow.edPrefs.fontScale || 1.0))
                    wrapMode: Text.Wrap
                    selectByMouse: true
                    persistentSelection: true
                    selectionColor: Theme.accent
                    selectedTextColor: "#1D1B17"
                    // 正文限宽居中（阅读宽度 ~820px，可在设置-外观关闭）
                    leftPadding: mainWindow.edPrefs.narrow !== false
                                  ? Math.max(56, Math.min(320, (editorHolder.width - 820) / 2)) : 40
                    rightPadding: mainWindow.edPrefs.narrow !== false
                                  ? Math.max(56, Math.min(320, (editorHolder.width - 820) / 2)) : 40
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
                    // 选区浮动工具栏（共写：选中即打磨）
                    onSelectedTextChanged: {
                        if (!bridge.isStreaming && selectedText.length >= 2 && activeFocus) {
                            var cr = editor.cursorRectangle
                            var gp = mapToItem(mainWindow.contentItem, cr.x, cr.y)
                            selToolbar.x = Math.min(mainWindow.width - selToolbar.width - 20, Math.max(340, gp.x))
                            selToolbar.y = Math.max(70, Math.min(mainWindow.height - 120, gp.y - 46))
                            selToolbar.visible = true
                        } else {
                            selToolbar.visible = false
                        }
                    }
                    onActiveFocusChanged: if (!activeFocus) selToolbar.visible = false
                }
            }

            }   // RowLayout（主编辑列：CwDialogueDock + 编辑器）

            // ---- 步骤决策门（人 AI 共写指挥台：每步确认 / 想法 / 回退）----
            StepGateBar {
                id: gateBar
                Layout.fillWidth: true
            }
            Connections {
                target: bridge
                function onGateAsked(key, chapter, summary) {
                    gateBar.showGate(key, chapter, summary)
                }
                function onGateClosed() {
                    gateBar.waiting = false   // 真机缺陷②：停止/失败/完本后清残留决策条
                }
            }
            Connections {
                target: bridge
                // 共写手动去AI味完成：改写文本进工作副本（未落盘），保存才提交
                function onCwProsePolished(polished) {
                    bridge.noteEditAction("去AI味")
                    editor.text = polished   // 触发 markEditorDirty → 未保存标记亮起
                }
            }
            Shortcut {
                sequence: "Return"
                enabled: gateBar.waiting
                onActivated: gateBar.doNext()
            }
            Shortcut {
                sequence: "Ctrl+Return"
                enabled: gateBar.waiting
                onActivated: gateBar.doNext()
            }
            Shortcut {
                sequence: "R"
                enabled: gateBar.waiting && gateBar.rollbackable
                onActivated: gateBar.doReturn()
            }

            // ---- 思维链面板（偏好持久化；流式结束后仍保留本轮内容供回看）----
            Rectangle {
                Layout.fillWidth: true
                visible: bridge.showReasoning && bridge.reasoningText !== ""
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
                            font.family: Theme.uiFont
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
                                id: findHot
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    editor.select(modelData.start, modelData.end)
                                    editor.forceActiveFocus()
                                }
                            }
                            ToolTip.visible: findHot.containsMouse && modelData.hint !== ""
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
        height: 24
        color: Theme.bgPanel
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
        z: 10

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 12
            Text {
                text: bridge.progressText !== "" ? "进度 " + bridge.progressText : "未打开项目"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Rectangle { width: 1; height: 12; color: Theme.border }
            Text {
                text: bridge.slotsText
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                elide: Text.ElideRight
                Layout.maximumWidth: 420
            }
            Rectangle { width: 1; height: 12; color: Theme.border }
            Item { Layout.fillWidth: true }
            Text {
                text: "今日 " + Number(bridge.totalTokens || 0).toLocaleString(Qt.locale(), 'f', 0) + " tokens · ≈ " + bridge.estCost
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                MouseArea {
                    id: statsHot
                    anchors.fill: parent
                    anchors.margins: -6
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        statsData = bridge.statsSummary()
                        statsDialog.open()
                    }
                }
                ToolTip.visible: statsHot.containsMouse
                ToolTip.text: "今日用量（本地统计，含全部调用）· 点击查看统计面板（章节/字数/成本）"
            }
            Rectangle { width: 1; height: 12; color: Theme.border }
            Text {
                text: "⚡ 用量"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
                MouseArea {
                    id: usageHot
                    anchors.fill: parent
                    anchors.margins: -6
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: usageDialog.open()
                }
                ToolTip.visible: usageHot.containsMouse
                ToolTip.text: "Token 用量统计（今日/本月/按模型，本地数据）"
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

    // ---- 选区浮动工具栏（圆角/阴影/动画 · 四动作直达局部改写）----
    Rectangle {
        id: selToolbar
        parent: mainWindow.contentItem
        visible: false
        z: 30
        width: selRow.implicitWidth + 20
        height: 36
        radius: 10
        color: Theme.bgCard
        opacity: visible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }

        Row {
            id: selRow
            anchors.centerIn: parent
            spacing: 4
            Repeater {
                model: [
                    { label: "改写", idea: "" },
                    { label: "扩写", idea: "扩写：把这一段写得更厚实，补充细节、动作与心理，不要偏离原意" },
                    { label: "精简", idea: "精简：删掉冗余，让这一段更干脆有力，保留核心信息" },
                    { label: "按想法改", idea: "" }
                ]
                delegate: Rectangle {
                    required property var modelData
                    width: stBtnText.implicitWidth + 16
                    height: 26
                    radius: 6
                    color: stBtnHover.containsMouse ? Theme.bgHover : "transparent"
                    Text {
                        id: stBtnText
                        anchors.centerIn: parent
                        text: modelData.label
                        color: Theme.textPrimary
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.uiFont
                    }
                    MouseArea {
                        id: stBtnHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            mainWindow.selStart = editor.selectionStart
                            mainWindow.selEnd = editor.selectionEnd
                            rewriteIdea.text = modelData.idea
                            selToolbar.visible = false
                            rewriteDialog.open()
                        }
                        ToolTip.visible: stBtnHover.containsMouse
                        ToolTip.text: "局部改写选中段落 · Ctrl+E"
                    }
                }
            }
        }
    }

    // ---- 沉浸阅读器（M2：三主题/排版/标注/书签/位置记忆）----
    ReaderView { id: readerView }

    // ---- 首启向导（T3.5）：未完成引导时自动弹出 ----
    WizardDialog { id: wizardDialog }

    // ---- Token 用量统计（插件）----
    UsageDialog { id: usageDialog }

    // ---- 关于（T4.2）：F1 呼出，含检查更新/日志目录/遥测开关 ----
    AboutDialog { id: aboutDialog }
    Shortcut {
        sequence: "F1"
        onActivated: aboutDialog.open()
    }

    // ---- 导出（M4：排版选项 + 预览 + 报告）----
    Dialog {
        id: exportDialog
        objectName: "exportDialog"
        parent: Overlay.overlay
        modal: true
        width: 680
        height: 520
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(24, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        property string fmt: "txt"
        property string sep: "blank"
        property int titleFmt: 0
        property string lastExport: ""

        function refreshPreview() {
            previewArea.text = bridge.exportPreviewText(exportDialog.sep, exportDialog.titleFmt)
        }

        header: Column {
            padding: 16
            spacing: 2
            Text {
                text: "导出全本"
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTitle
                font.bold: true
            }
            Text {
                text: "排版选项即时预览（前两章实际效果）· 导出后显示报告"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
            }
        }
        contentItem: ColumnLayout {
            spacing: 10

            // 格式
            RowLayout {
                spacing: 6
                Text { text: "格式"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                Repeater {
                    model: [{ t: "txt（平台上传标准）", v: "txt" }, { t: "epub（阅读器通用）", v: "epub" }]
                    delegate: Rectangle {
                        required property var modelData
                        height: 26; radius: 7
                        width: fmtText.implicitWidth + 18
                        color: exportDialog.fmt === modelData.v ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                        border.width: 1
                        border.color: exportDialog.fmt === modelData.v ? Theme.accent : Theme.border
                        Text { id: fmtText; anchors.centerIn: parent; text: modelData.t
                               color: exportDialog.fmt === modelData.v ? Theme.accent : Theme.textTertiary
                               font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: { exportDialog.fmt = modelData.v; exportDialog.refreshPreview() } }
                    }
                }
                Item { Layout.fillWidth: true }
            }
            // 分隔与标题（txt 有效）
            RowLayout {
                visible: exportDialog.fmt === "txt"
                spacing: 6
                Text { text: "章节分隔"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                Repeater {
                    model: [{ t: "空行", v: "blank" }, { t: "分隔线", v: "line" }, { t: "分页符", v: "page" }]
                    delegate: Rectangle {
                        required property var modelData
                        height: 24; radius: 6
                        width: sepText.implicitWidth + 14
                        color: exportDialog.sep === modelData.v ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                        border.width: 1
                        border.color: exportDialog.sep === modelData.v ? Theme.accent : Theme.border
                        Text { id: sepText; anchors.centerIn: parent; text: modelData.t
                               color: exportDialog.sep === modelData.v ? Theme.accent : Theme.textTertiary
                               font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: { exportDialog.sep = modelData.v; exportDialog.refreshPreview() } }
                    }
                }
                Item { Layout.fillWidth: true }
                Text { text: "标题格式"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                Repeater {
                    model: 4
                    delegate: Rectangle {
                        required property int index
                        height: 24; radius: 6
                        width: tfText.implicitWidth + 14
                        color: exportDialog.titleFmt === index ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                        border.width: 1
                        border.color: exportDialog.titleFmt === index ? Theme.accent : Theme.border
                        Text { id: tfText; anchors.centerIn: parent
                               text: ["第X章 标题", "第X章·标题", "仅标题", "无标题"][index]
                               color: exportDialog.titleFmt === index ? Theme.accent : Theme.textTertiary
                               font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: { exportDialog.titleFmt = index; exportDialog.refreshPreview() } }
                    }
                }
            }
            // 预览
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.rCard
                color: Theme.bgLog
                clip: true
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 2
                    TextArea {
                        id: previewArea
                        readOnly: true
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    visible: previewArea.text === ""
                    text: "（预览）"
                    color: Theme.textTertiary
                }
            }
            // 导出结果（成功后显示完整路径 + 文件管理器定位入口）
            RowLayout {
                Layout.fillWidth: true
                visible: exportDialog.lastExport !== ""
                spacing: 8
                Text {
                    text: "已导出"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
                Text {
                    id: exportPathText
                    Layout.fillWidth: true
                    text: exportDialog.lastExport
                    color: Theme.accent
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.WrapAnywhere
                    maximumLineCount: 2
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.revealPath(exportDialog.lastExport)
                    }
                }
                AppButton {
                    text: "打开所在文件夹"
                    height: 24
                    onClicked: bridge.revealPath(exportDialog.lastExport)
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "简介与标签…"
                enabled: bridge.hasProject
                onClicked: blurbDialog.open()
            }
            AppButton {
                text: "备份项目 zip"
                onClicked: bridge.backupProject()
            }
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: exportDialog.close()
            }
            AppButton {
                text: "导出"
                kind: "primary"
                onClicked: {
                    // 导出后不立即关闭：显示完整路径，可一键定位到文件
                    exportDialog.lastExport = bridge.exportProjectOpts(exportDialog.fmt, exportDialog.sep, exportDialog.titleFmt)
                }
            }
        }
        onOpened: {
            lastExport = ""
            refreshPreview()
        }
    }

    // ---- 发布物料：标签与简介（一键生成，粘贴到平台后台）----
    Dialog {
        id: blurbDialog
        objectName: "blurbDialog"
        parent: Overlay.overlay
        modal: true
        width: 660
        height: 560
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(24, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        property string content: ""
        property bool busy: false

        header: Column {
            padding: 16
            spacing: 2
            Text {
                text: "发布物料 · 标签与简介"
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTitle
                font.bold: true
            }
            Text {
                text: "据题材定位 + 全书大纲生成 · 自动保存到 设定/简介与标签.md · 流水线面板亦可生成"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
            }
        }
        contentItem: ColumnLayout {
            spacing: 10
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.rCard
                color: Theme.bgLog
                border.width: 1
                border.color: Theme.border
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        readOnly: true
                        text: blurbDialog.content !== "" ? blurbDialog.content
                              : (blurbDialog.busy ? "" : "（尚未生成——点下方「生成简介与标签」，约 30-60 秒）")
                        color: blurbDialog.content !== "" ? Theme.textSecondary : Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    visible: blurbDialog.busy
                    text: "生成中…（辅助槽，约 30-60 秒）"
                    color: Theme.accent
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "复制全文"
                enabled: blurbDialog.content !== "" && !blurbDialog.busy
                onClicked: bridge.copyText(blurbDialog.content)
            }
            AppButton {
                text: blurbDialog.content === "" ? "生成简介与标签" : "重新生成"
                kind: "primary"
                enabled: !bridge.isRunning && !blurbDialog.busy
                onClicked: {
                    blurbDialog.busy = true
                    bridge.generateBlurb()
                }
            }
            AppButton {
                text: "关闭"
                kind: "ghost"
                onClicked: blurbDialog.close()
            }
        }
        onOpened: {
            content = bridge.blurbText()
        }
    }
    Connections {
        target: bridge
        function onBlurbGenerated(ok, text) {
            blurbDialog.busy = false
            if (ok)
                blurbDialog.content = text
        }
    }

    // ---- 锁定被字数闸门拦截：强锁确认框 ----
    property int lockBlockNum: 0
    property string lockBlockReason: ""
    property int lockBlockActual: 0
    property int lockBlockTarget: 0
    property string lockBlockKind: "word"   // word=字数未达标 | contract=正则 must 违规
    Connections {
        target: bridge
        function onLockBlocked(num, reason, actual, target, kind) {
            mainWindow.lockBlockNum = num
            mainWindow.lockBlockReason = reason
            mainWindow.lockBlockActual = actual
            mainWindow.lockBlockTarget = target
            mainWindow.lockBlockKind = kind || "word"
            forceLockDialog.open()
        }
    }
    Dialog {
        id: forceLockDialog
        objectName: "forceLockDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: mainWindow.lockBlockKind === "contract"
                   ? "第 " + mainWindow.lockBlockNum + " 章违反本书正则契约，仍要锁定？"
                   : "第 " + mainWindow.lockBlockNum + " 章字数未达标，仍要锁定？"
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
                text: mainWindow.lockBlockReason
                color: Theme.danger
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                visible: mainWindow.lockBlockKind !== "contract"
                width: parent.width
                text: "当前 " + Number(mainWindow.lockBlockActual).toLocaleString(Qt.locale(), 'f', 0)
                      + " 字 / 目标 " + Number(mainWindow.lockBlockTarget).toLocaleString(Qt.locale(), 'f', 0)
                      + " 字。锁定后本章反哺登记照常进行，但短章事实会被留痕；解锁后可继续扩写。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                visible: mainWindow.lockBlockKind === "contract"
                width: parent.width
                text: "这条规则是本地按你声明的正则确定性命中的，不是模型的主观判断。"
                      + "若规则本身已过时，请改 设定/正则.md（或给它加 ｜disabled）而不是强锁绕过；"
                      + "确属有意为之则强锁，违规内容会写进本章的强锁留痕。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "先不锁定"
                kind: "ghost"
                onClicked: forceLockDialog.close()
            }
            AppButton {
                text: "仍要锁定"
                kind: "primary"
                onClicked: { bridge.forceConfirmChapterLocked(); forceLockDialog.close() }
            }
        }
    }

    // ---- 统计面板（管理者视角：章节/字数/成本）----
    property var statsData: ({})
    Dialog {
        id: statsDialog
        objectName: "statsDialog"
        parent: Overlay.overlay
        modal: true
        width: 420
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "统计 · " + bridge.bookTitle
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: GridLayout {
            columns: 2
            columnSpacing: 16
            rowSpacing: 10
            Repeater {
                model: [
                    { k: "已写章节", v: (mainWindow.statsData.chapters || 0) + " 章" },
                    { k: "全书字数", v: Number(mainWindow.statsData.words || 0).toLocaleString(Qt.locale(), 'f', 0) + " 字" },
                    { k: "平均章节", v: Number(mainWindow.statsData.avgWords || 0).toLocaleString(Qt.locale(), 'f', 0) + " 字" },
                    { k: "今日新增", v: Number(mainWindow.statsData.todayWords || 0).toLocaleString(Qt.locale(), 'f', 0) + " 字" },
                    { k: "本周新增", v: Number(mainWindow.statsData.weekWords || 0).toLocaleString(Qt.locale(), 'f', 0) + " 字" },
                    { k: "今日 token", v: Number(mainWindow.statsData.tokens || 0).toLocaleString(Qt.locale(), 'f', 0) },
                    { k: "预估成本", v: mainWindow.statsData.cost || "¥0.00" }
                ]
                delegate: Column {
                    required property var modelData
                    spacing: 2
                    Text { text: modelData.k; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                    Text { text: modelData.v; color: Theme.textPrimary; font.pixelSize: Theme.fsBig; font.family: Theme.uiFont }
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton { text: "关闭"; kind: "ghost"; onClicked: statsDialog.close() }
            AppButton { text: "备份项目 zip"; kind: "primary"; onClicked: bridge.backupProject() }
        }
    }

    // ---- 全局 Toast ----
    Rectangle {
        id: toastBar
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: Math.min(560, toastText.implicitWidth + 44)
        height: 36
        radius: Theme.rBtn
        color: Theme.bgCard
        border.width: 1
        border.color: toastBar.toastLevel === "error" ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.5)
                 : toastBar.toastLevel === "warn" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
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
        // 打字机流式（S4）：全文进缓冲，非平滑模式直接展示
        function onLiveDraftChanged() {
            mainWindow.streamFull = bridge.liveDraftText
            if (!mainWindow.edPrefs.streamSmooth)
                mainWindow.streamShown = bridge.liveDraftText
        }
        function onStreamStageChanged() {
            mainWindow.streamFull = ""
            mainWindow.streamShown = ""
        }
    }

    // ---- 局部重写对话框（选中段落 + 想法 → AI 只改这一段）----
    Dialog {
        id: rewriteDialog
        objectName: "rewriteDialog"
        parent: Overlay.overlay
        modal: true
        width: 620
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "局部重写选中段落"
            color: Theme.textPrimary
            font.family: Theme.uiFont
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
                color: Theme.textSecondary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Rectangle {
                width: parent.width
                height: 90
                radius: Theme.rBtn
                color: Theme.bgHover
                border.width: 1
                border.color: Theme.border
                clip: true
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        text: editor.selectedText !== "" ? editor.selectedText : ""
                        readOnly: true
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
            }
            // 改写上下文选项（共写：AI 看多少上下文来改这一段）
            Text {
                text: "改写上下文："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            Row {
                spacing: 6
                Repeater {
                    model: [["仅选中段", "only"], ["前后各一段", "neighbor"], ["带全章", "full"], ["全章+设定", "setting"]]
                    delegate: Rectangle {
                        required property var modelData
                        width: ctxText.implicitWidth + 18
                        height: 24
                        radius: 6
                        color: mainWindow.rewriteCtxMode === modelData[1] ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                        border.width: 1
                        border.color: mainWindow.rewriteCtxMode === modelData[1] ? Theme.accent : Theme.border
                        Text {
                            id: ctxText
                            anchors.centerIn: parent
                            text: modelData[0]
                            color: mainWindow.rewriteCtxMode === modelData[1] ? Theme.accent : Theme.textSecondary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: mainWindow.rewriteCtxMode = modelData[1] }
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
                        font.family: Theme.uiFont
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
                    // 上下文四档真裁剪：only=无上下文 neighbor=前后各一段 full=全章 setting=全章+核心设定
                    var mode = mainWindow.rewriteCtxMode
                    var before = "", after = ""
                    if (mode === "neighbor") {
                        // 只取选中段之前/之后的各一个段落（按空行分段）
                        var b = editor.getText(0, mainWindow.selStart).split(/\n\s*\n/)
                        var a = editor.getText(mainWindow.selEnd, editor.text.length).split(/\n\s*\n/)
                        before = b.length > 1 ? b[b.length - 2] : (b[0] || "")
                        after = a.length > 1 ? a[1] : (a[0] || "")
                    } else if (mode === "full" || mode === "setting") {
                        before = editor.getText(0, mainWindow.selStart)
                        after = editor.getText(mainWindow.selEnd, editor.text.length)
                    }
                    var sel = editor.getText(mainWindow.selStart, mainWindow.selEnd)
                    bridge.rewriteSelection(before, sel, after, rewriteIdea.text, mode)
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
                        // 多段连改：应用后自动选中下一段，形成"逐段打磨"工作流
                        var nextStart = mainWindow.selStart + result.length
                        var text = editor.text
                        while (nextStart < text.length && /\s/.test(text[nextStart])) nextStart++
                        if (nextStart < text.length - 2) {
                            var paraEnd = text.indexOf("\n", nextStart)
                            if (paraEnd < 0 || paraEnd > nextStart + 800) paraEnd = Math.min(text.length, nextStart + 800)
                            editor.select(nextStart, paraEnd)
                            mainWindow.selStart = nextStart
                            mainWindow.selEnd = paraEnd
                            bridge.showToast("ok", "已应用并选中下一段——继续「改写/扩写/精简」即多段连改")
                        } else {
                            mainWindow.selStart = -1
                            mainWindow.selEnd = -1
                        }
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
        objectName: "unsavedDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "有未保存的修改"
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
        objectName: "versionsDialog"
        parent: Overlay.overlay
        modal: true
        width: 820
        height: 540
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(24, Math.round((parent.height - height) / 2)) : 0
        padding: 0
        background: DialogBg {}
        header: Column {
            padding: 16
            spacing: 2
            Text {
                text: "版本历史 · 第 " + bridge.currentChapterNum + " 章（保存驱动：仅「保存」产生版本）"
                color: Theme.textPrimary
                font.family: Theme.uiFont
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
                                    font.family: Theme.uiFont
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
                                color: model.op === "del" ? Theme.danger
                                     : model.op === "add" ? Theme.success : Theme.textSecondary
                                font.family: Theme.uiFont
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
        objectName: "recoverDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "发现未保存草稿"
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

    // ---- v0.13：6 维审校问题对话框（A/B/C 三选一）----
    // issues/verdict 由下方 onReviewIssuesChanged 统一赋值：
    // 声明处绑定只在组件初始化时求值一次（启动时项目未开），会造成 verdict 永远为空落到兜底文案
    ReviewIssueDialog {
        id: reviewIssueDialog
        objectName: "reviewIssueDialog"
    }
    Connections {
        target: bridge
        function onReviewIssuesChanged() {
            var items = bridge.reviewIssues()
            reviewIssueDialog.verdict = bridge.reviewVerdict()
            if (items && items.length > 0) {
                reviewIssueDialog.issues = items
                reviewIssueDialog.open()
            }
        }
    }

    // ---- 待修章节汇总对话框（一键修复入口；流水线跑完有待修章自动弹出）----
    NeedsFixDialog {
        id: needsFixDialog
        objectName: "needsFixDialog"
    }
    Connections {
        target: bridge
        function onNeedsFixReady() {
            needsFixDialog.refresh()
            needsFixDialog.open()
        }
    }

    // ---- P2：章级生成配置快照对话框（队列行右键「查看生成配置…」）----
    GenConfigDialog {
        id: genConfigDialog
        objectName: "genConfigDialog"
    }
    Connections {
        target: bridge
        function onGenConfigReady(num) { genConfigDialog.showFor(num) }
    }

    // ---- v0.13：Ctrl+T 切换主题快捷键（夜间/羊皮纸/纯白）----
    Shortcut {
        sequence: "Ctrl+T"
        onActivated: {
            var cur = bridge.currentTheme()
            var next = cur === "qianbi_night" ? "qianbi_parchment"
                     : cur === "qianbi_parchment" ? "qianbi_plain" : "qianbi_night"
            bridge.setTheme(next)
        }
    }
}
