import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// M2 阅读器体系 · 全屏沉浸阅读（成熟小说阅读器品质）
//   三主题（夜间/羊皮纸/纯白）· 字号5档 · 行距3档 · 宋/黑
//   滚动 / 左右翻页 · 右侧抽屉（目录 / 标注 / 书签 三标签）
//   选中标注（三色高亮 · 批注 · 灵感→创作笔记）· 位置记忆
//   未定稿徽章（工作副本/流式中实时更新）· 首行缩进富文本
// ============================================================
Rectangle {
    id: reader
    anchors.fill: parent
    z: 50
    visible: opacity > 0.01
    opacity: 0
    color: th.bg

    property int curNum: 0
    property string curTitle: ""
    property string bodyText: ""
    property string proseText: ""        // 正文（含未保存工作副本）
    property string outlineText: ""      // 本章细纲；空=没有，切换器随之隐藏
    property bool showOutline: false
    property bool isDraft: false
    property bool isLive: false
    property var prefs: ({ theme: "night", fontScale: 1.0, lineHeight: 1.8, serif: true, paged: false })
    property var store: ({ annotations: [], bookmarks: [], position: 0.0 })
    property int progressPercent: 0
    property string drawerTab: "toc"
    property alias drawerOpened: drawer.opened   // 测试/外部驱动用

    // 三主题独立配色（不影响写作主题）
    readonly property var themes: ({
        night:     { bg: "#0C0E12", text: "#E6E9EF", dim: "#8A94A2", faint: "#5A6370",
                     bar: "#12151A", card: "#171B21", border: "#24E9ECF1",
                     accent: "#4E9CFF", sel: "#2B4C75",
                     hlY: "#8A6F1E", hlG: "#3F7D5F", hlR: "#8F4A3B", glow: "#12FFFFFF" },
        parchment: { bg: "#F5EDD8", text: "#43392A", dim: "#94886C", faint: "#B3A98D",
                     bar: "#EDE2C6", card: "#F9F3E1", border: "#D9CCA8",
                     accent: "#9A7420", sel: "#C9B77E",
                     hlY: "#E5C96B", hlG: "#A7CBA4", hlR: "#DE9C8A", glow: "#0A43392A" },
        white:     { bg: "#FFFFFF", text: "#262626", dim: "#8A8A8A", faint: "#B5B5B5",
                     bar: "#F5F5F3", card: "#FAFAF8", border: "#E3E3DF",
                     accent: "#B07E1E", sel: "#D8CBA4",
                     hlY: "#F2DA7C", hlG: "#B5D9B2", hlR: "#E8A794", glow: "#08262626" }
    })
    readonly property var th: themes[prefs.theme] || themes.night
    readonly property int fontSize: Math.round(18 * (prefs.fontScale || 1.0))
    readonly property real lineH: prefs.lineHeight || 1.8
    readonly property var chapters: bridge.readerChapterList()

    // ---- 生命周期 ----
    function open(initialNum, workText) {
        prefs = bridge.readerPrefs()
        loadChapter(initialNum, workText)
        opacity = 1
        drawer.opened = false
    }
    function close() {
        savePosition()
        hideDrawer()
        opacity = 0
    }

    function loadChapter(num, workTextOverride) {
        if (curNum) savePosition()
        var ch = bridge.readerChapter(num)
        curNum = num
        curTitle = ""
        for (var i = 0; i < chapters.length; i++)
            if (chapters[i].num === num) curTitle = chapters[i].title
        isDraft = ch.isDraft || (workTextOverride !== undefined && workTextOverride !== "")
        isLive = ch.isLive
        proseText = (workTextOverride !== undefined && workTextOverride !== "")
                    ? workTextOverride : ch.text
        outlineText = bridge.readerChapterOutline(num)
        if (showOutline && outlineText === "") showOutline = false   // 这章没细纲
        applyView()
        store = bridge.readStore(num)
        render()
        var pos = store.position || 0
        Qt.callLater(function () {
            var maxY = Math.max(1, flick.contentHeight - flick.height)
            flick.contentY = pos * maxY
        })
    }

    function savePosition() {
        if (!curNum || flick.contentHeight <= flick.height) return
        bridge.saveReadPosition(curNum, flick.contentY / (flick.contentHeight - flick.height))
    }

    function applyView() {
        bodyText = showOutline ? outlineText : proseText
        render()
    }

    function setView(outline) {
        if (outline && outlineText === "") return
        showOutline = outline
        savePosition()
        applyView()
        Qt.callLater(function () { flick.contentY = 0 })
    }

    function render() {
        textArea.text = toHtml(bodyText)
    }

    // 纯文本 → 富文本：标题层级 + 首行缩进 + 行距 + 中文引号 + 已存高亮着色
    function toHtml(text) {
        function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
        // 直引号 → 中文引号（按出现次序配对；只作用于正文，不影响任何标记）
        function cnQuotes(s) {
            var out = "", dq = true, sq = true
            for (var i = 0; i < s.length; i++) {
                var ch = s.charAt(i)
                if (ch === '"') { out += dq ? "\u201C" : "\u201D"; dq = !dq }
                else if (ch === "'") { out += sq ? "\u2018" : "\u2019"; sq = !sq }
                else out += ch
            }
            return out
        }
        var hl = { highlight_yellow: th.hlY, highlight_green: th.hlG, highlight_red: th.hlR }
        var out = []
        var paras = String(text).split(/\n+/)
        for (var i = 0; i < paras.length; i++) {
            var head = paras[i].match(/^\s*(#{1,3})\s*(.+)$/)
            if (head) {
                // Markdown 标题 → 真标题层级（更大字号加粗，不缩进，带节间距）
                var lvl = head[1].length
                var hSize = lvl === 1 ? Math.round(fontSize * 1.5) : Math.round(fontSize * 1.25)
                out.push("<p style=\"text-indent:0; margin:"
                         + (lvl === 1 ? "0.2em 0 1.1em 0" : "1em 0 0.6em 0")
                         + "; line-height:1.5\"><b><span style=\"font-size:" + hSize + "px\">"
                         + esc(cnQuotes(head[2])) + "</span></b></p>")
                continue
            }
            var p = esc(cnQuotes(paras[i]))
            for (var a = 0; a < store.annotations.length; a++) {
                var ann = store.annotations[a]
                var qRaw = esc(ann.quote || "")
                var qCn = esc(cnQuotes(ann.quote || ""))
                if (qRaw.length > 1 && hl[ann.kind]) {
                    // 引文按「转换后 → 原文」两种形态都试一次（染色全部出现）
                    if (p.indexOf(qCn) >= 0)
                        p = p.split(qCn).join("<span style=\"background-color:" + hl[ann.kind] + "\">" + qCn + "</span>")
                    else if (p.indexOf(qRaw) >= 0)
                        p = p.split(qRaw).join("<span style=\"background-color:" + hl[ann.kind] + "\">" + qRaw + "</span>")
                }
            }
            out.push("<p style=\"text-indent:2em; margin:0 0 0.35em 0; line-height:" + lineH + "\">" + p + "</p>")
        }
        return out.join("")
    }

    function refreshStore() { store = bridge.readStore(curNum) }

    function jumpToRatio(pos) {
        var maxY = Math.max(1, flick.contentHeight - flick.height)
        flick.contentY = pos * maxY
    }

    function pageStep(dir) {
        var maxY = Math.max(0, flick.contentHeight - flick.height)
        var next = flick.contentY + dir * flick.height * 0.88
        if (next >= maxY && dir > 0) { nextChapter(); return }
        if (next <= 0 && dir < 0) { prevChapter(); return }
        flick.contentY = Math.min(maxY, Math.max(0, next))
    }

    function adjacent(dir) {
        for (var i = 0; i < chapters.length; i++)
            if (chapters[i].num === curNum) return chapters[i + dir] || null
        return null
    }
    function nextChapter() { var c = adjacent(1); if (c) loadChapter(c.num); else toast("已是最后一章") }
    function prevChapter() { var c = adjacent(-1); if (c) loadChapter(c.num); else toast("已是第一章") }
    function toast(msg) { bridge.showToast("warn", msg) }

    function showDrawer(tab) {
        drawerTab = tab
        if (tab === "marks") refreshStore()
        drawer.opened = true
    }
    function hideDrawer() { drawer.opened = false }

    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

    // ---- 顶部栏 ----
    Rectangle {
        id: topBar
        anchors.top: parent.top
        width: parent.width
        height: 54
        color: th.bar
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: th.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 8

            RToolButton { icon: "left"; label: "退出"; onClicked: reader.close() }

            Rectangle { width: 1; height: 22; color: th.border }

            RSegment {
                visible: reader.outlineText !== ""
                options: ["正文", "细纲"]
                values: [false, true]
                current: reader.showOutline
                onPicked: (v) => reader.setView(v)
            }

            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                RowLayout {
                    spacing: 8
                    Text {
                        text: "第 " + curNum + " 章"
                        color: th.accent
                        font.family: Theme.monoFont
                        font.pixelSize: 13
                    }
                    Text {
                        Layout.fillWidth: true
                        text: curTitle
                        color: th.text
                        font.family: Theme.serifFont
                        font.pixelSize: 16
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    // 未定稿徽章（工作副本 / 流式中）
                    Rectangle {
                        visible: isDraft || isLive
                        height: 20; radius: 10
                        width: badgeText.implicitWidth + 16
                        color: isLive ? Qt.rgba(0.89, 0.70, 0.36, 0.16) : Qt.rgba(0.86, 0.47, 0.38, 0.14)
                        border.width: 1
                        border.color: isLive ? th.accent : th.hlR
                        Text {
                            id: badgeText
                            anchors.centerIn: parent
                            text: isLive ? "生成中" : "未定稿"
                            color: isLive ? th.accent : th.hlR
                            font.family: Theme.uiFont; font.pixelSize: 11
                        }
                        // 生成中呼吸动画
                        SequentialAnimation on opacity {
                            running: isLive; loops: Animation.Infinite
                            NumberAnimation { to: 0.45; duration: 700 }
                            NumberAnimation { to: 1; duration: 700 }
                        }
                    }
                }
                Text {
                    visible: isDraft || isLive
                    text: isLive ? "AI 正在写作本章 · 流式内容实时更新"
                         : "当前为未保存的工作副本 · 保存后才成为版本"
                    color: th.faint
                    font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro
                }
            }

            Text {
                visible: !isDraft && !isLive
                text: bodyText.replace(/\s/g, "").length + " 字"
                color: th.faint
                font.family: Theme.monoFont; font.pixelSize: 11
            }

            RToolButton { icon: "chapters"; label: ""; tip: "目录"; active: drawer.opened && drawerTab === "toc"; onClicked: drawer.opened && drawerTab === "toc" ? hideDrawer() : showDrawer("toc") }
            RToolButton { icon: "notes"; label: ""; tip: "标注与书签"; active: drawer.opened && drawerTab === "marks"; onClicked: drawer.opened && drawerTab === "marks" ? hideDrawer() : showDrawer("marks") }
            RToolButton { icon: "settings"; label: ""; tip: "阅读排版（主题/字号/行距）"; active: prefsPanel.visible; onClicked: prefsPanel.visible ? prefsPanel.visible = false : prefsPanel.visible = true }
            RToolButton { icon: "bookmark"; label: ""; tip: "在当前位置加书签"; onClicked: {
                bridge.addBookmark(curNum, flick.contentY / Math.max(1, flick.contentHeight - flick.height), "")
                refreshStore()
            } }
        }
    }

    // ---- 正文阅读区 ----
    Flickable {
        id: flick
        anchors.top: topBar.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left
        anchors.right: drawer.left
        contentWidth: width
        contentHeight: textArea.implicitHeight + 80
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        maximumFlickVelocity: 3200

        property real lastReported: -1
        onContentYChanged: {
            var maxY = Math.max(1, contentHeight - height)
            var pct = Math.round(contentY / maxY * 100)
            if (pct !== reader.progressPercent) reader.progressPercent = pct
        }
        onMovementEnded: savePosition()

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle { implicitWidth: 5; radius: 2.5; color: reader.th.faint }
        }

        TextArea {
            id: textArea
            x: Math.max(28, (flick.width - 740) / 2)
            width: Math.min(flick.width - 56, 740)
            readOnly: true
            textFormat: TextEdit.RichText
            wrapMode: Text.Wrap
            selectByMouse: true
            persistentSelection: false
            color: reader.th.text
            selectionColor: reader.th.sel
            selectedTextColor: reader.th.bg
            font.family: reader.prefs.serif !== false ? Theme.serifFont : "Microsoft YaHei UI"
            font.pixelSize: reader.fontSize
            topPadding: 34
            bottomPadding: 60
            background: Rectangle { color: "transparent" }

            onSelectedTextChanged: {
                if (selectedText.length >= 2 && !reader.isLive) {
                    var cr = cursorRectangle
                    var gp = mapToItem(reader, cr.x, cr.y)
                    annBar.x = Math.max(16, Math.min(reader.width - annBar.width - 16,
                                                     gp.x - annBar.width / 2))
                    annBar.y = Math.max(topBar.height + 8,
                                        Math.min(reader.height - bottomBar.height - annBar.height - 8,
                                                 gp.y - annBar.height - 10))
                    annBar.show()
                } else {
                    annBar.hide()
                }
            }
        }
    }

    // 流式中实时更新
    Connections {
        target: bridge
        function onLiveDraftChanged() {
            if (reader.isLive && reader.curNum === bridge.currentChapterNum)
                reader.bodyText = bridge.liveDraftText
        }
    }
    onBodyTextChanged: {
        if (opacity > 0.5) {
            var keep = flick.contentY
            render()
            if (isLive) Qt.callLater(function () { flick.contentY = keep })
        }
    }
    onPrefsChanged: if (opacity > 0.5) render()

    // ---- 底部进度栏 ----
    Rectangle {
        id: bottomBar
        anchors.bottom: parent.bottom
        width: parent.width
        height: 46
        color: th.bar
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: th.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 14

            RToolButton { icon: "left"; label: "上一章"; dimmed: !reader.adjacent(-1); onClicked: reader.prevChapter() }
            RToolButton { icon: "right"; label: "下一章"; dimmed: !reader.adjacent(1); onClicked: reader.nextChapter() }

            Item { Layout.fillWidth: true }

            Text {
                text: reader.progressPercent + "%"
                color: th.accent
                font.family: Theme.monoFont; font.pixelSize: 12
                Layout.minimumWidth: 40
                horizontalAlignment: Text.AlignRight
            }
            Rectangle {
                Layout.preferredWidth: 220
                Layout.maximumWidth: 260
                height: 4; radius: 2
                color: Qt.rgba(0.5, 0.5, 0.5, 0.18)
                Rectangle {
                    width: parent.width * reader.progressPercent / 100
                    height: parent.height; radius: 2
                    color: th.accent
                    Behavior on width { NumberAnimation { duration: 120 } }
                }
            }
            Text {
                text: (prefs.paged ? "翻页模式" : "滚动模式") + " · Esc 退出"
                color: th.faint
                font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro
            }
        }
    }

    // ---- 翻页热区（两侧，带 hover 提示箭头）----
    Repeater {
        model: [{ d: -1, x: 0, a: "‹" }, { d: 1, x: reader.width - 64, a: "›" }]
        Rectangle {
            required property var modelData
            y: topBar.height; height: reader.height - topBar.height - bottomBar.height
            x: modelData.x; width: 64
            color: hot.containsMouse ? Qt.rgba(0.5, 0.5, 0.5, 0.08) : "transparent"
            Text {
                anchors.centerIn: parent
                text: modelData.a
                color: reader.th.faint
                font.pixelSize: 30
                opacity: hot.containsMouse ? 1 : 0.35
                Behavior on opacity { NumberAnimation { duration: 150 } }
            }
            MouseArea {
                id: hot
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: reader.pageStep(modelData.d)
            }
        }
    }

    // ---- 选中标注工具条 ----
    Rectangle {
        id: annBar
        visible: opacity > 0.05
        opacity: 0
        width: annRow.implicitWidth + 22
        height: 40
        radius: 12
        color: th.card
        border.width: 1
        border.color: th.border
        z: 60

        function show() { opacity = 1; hideTimer.restart() }
        function hide() { opacity = 0 }

        Behavior on opacity { NumberAnimation { duration: 130 } }
        Timer { id: hideTimer; interval: 6000; onTriggered: annBar.hide() }

        Row {
            id: annRow
            anchors.centerIn: parent
            spacing: 12

            Repeater {
                model: [{ k: "highlight_yellow", c: th.hlY, t: "黄色高亮" },
                        { k: "highlight_green", c: th.hlG, t: "绿色高亮" },
                        { k: "highlight_red", c: th.hlR, t: "红色高亮" }]
                delegate: Rectangle {
                    required property var modelData
                    width: 20; height: 20; radius: 10
                    color: modelData.c
                    border.width: 2
                    border.color: dotHot.containsMouse ? th.accent : "transparent"
                    anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                        id: dotHot
                        anchors.fill: parent
                        anchors.margins: -5
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        ToolTip.visible: containsMouse
                        ToolTip.text: modelData.t
                        onClicked: {
                            bridge.addAnnotation(curNum, modelData.k, textArea.selectedText, "",
                                                 flick.contentY / Math.max(1, flick.contentHeight - flick.height))
                            refreshStore()
                            render()
                            textArea.deselect()
                            annBar.hide()
                        }
                    }
                }
            }

            Rectangle { width: 1; height: 20; color: th.border; anchors.verticalCenter: parent.verticalCenter }

            RMiniText { text: "批注"; color: reader.th.text; onClicked: { notePopup.isIdea = false; notePopup.open() } }
            RMiniText { text: "灵感"; color: reader.th.accent; onClicked: { notePopup.isIdea = true; notePopup.open() } }
        }
    }

    // 批注 / 灵感 输入弹层
    Popup {
        id: notePopup
        property bool isIdea: false
        anchors.centerIn: parent
        width: 440
        height: 190
        modal: true
        padding: 0
        background: Rectangle { radius: 14; color: reader.th.card; border.width: 1; border.color: reader.th.border }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 } }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10
            Text {
                text: notePopup.isIdea ? "灵感标记 → 自动进创作笔记（注入后续章节）"
                                       : "批注（待改点 / 疑问 / 想法，存入本章标注）"
                color: reader.th.text
                font.family: Theme.uiFont; font.pixelSize: 13; font.bold: true
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                TextArea {
                    id: noteInput
                    color: reader.th.text
                    font.family: Theme.uiFont; font.pixelSize: 13
                    wrapMode: Text.Wrap
                    placeholderText: notePopup.isIdea ? "例：这里可以埋一条伏笔，后面让主角的旧识认出他…" : "例：这段节奏太拖，定稿前要压缩"
                    placeholderTextColor: reader.th.faint
                    background: Rectangle { radius: 8; color: Qt.rgba(0.5, 0.5, 0.5, 0.12) }
                }
            }
            Row {
                spacing: 8
                layoutDirection: Qt.RightToLeft
                Layout.fillWidth: true
                RToolButton { icon: "check"; label: notePopup.isIdea ? "记入笔记" : "保存批注"; accent: true; onClicked: {
                    if (notePopup.isIdea) {
                        if (noteInput.text.trim() !== "")
                            bridge.addReaderIdea(curNum, noteInput.text.trim())
                    } else {
                        bridge.addAnnotation(curNum, "comment", textArea.selectedText, noteInput.text,
                                             flick.contentY / Math.max(1, flick.contentHeight - flick.height))
                        refreshStore()
                    }
                    noteInput.text = ""
                    textArea.deselect()
                    annBar.hide()
                    notePopup.close()
                } }
                RToolButton { icon: "close"; label: "取消"; onClicked: notePopup.close() }
            }
        }
    }

    // ---- 右侧抽屉（目录 / 标注·书签）----
    Rectangle {
        id: drawer
        visible: drawer.opened
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.bottom: bottomBar.top
        width: 300
        color: th.card
        Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: th.border }

        property bool opened: false

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // 抽屉标签
            Rectangle {
                Layout.fillWidth: true
                height: 44
                color: th.bar
                Row {
                    anchors.centerIn: parent
                    spacing: 4
                    RTabBtn { text: "目录"; active: reader.drawerTab === "toc"; onClicked: reader.drawerTab = "toc" }
                    RTabBtn { text: "标注与书签"; active: reader.drawerTab === "marks"; onClicked: { reader.drawerTab = "marks"; reader.refreshStore() } }
                }
            }

            // 目录
            ListView {
                visible: reader.drawerTab === "toc"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: reader.chapters
                spacing: 2
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: 44
                    radius: 8
                    color: modelData.num === reader.curNum ? Qt.rgba(0.89, 0.70, 0.36, 0.15)
                         : tocHot.containsMouse ? Qt.rgba(0.5, 0.5, 0.5, 0.1) : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 10
                        spacing: 8
                        Text {
                            text: String(modelData.num).padStart(3, "0")
                            color: modelData.num === reader.curNum ? reader.th.accent : reader.th.faint
                            font.family: Theme.monoFont; font.pixelSize: 11
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.title
                            color: modelData.num === reader.curNum ? reader.th.accent : reader.th.text
                            font.family: Theme.serifFont; font.pixelSize: 13
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.words + "字"
                            color: reader.th.faint
                            font.family: Theme.monoFont; font.pixelSize: Theme.fsMicro
                        }
                    }
                    MouseArea {
                        id: tocHot
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: reader.loadChapter(modelData.num)
                    }
                }
            }

            // 标注与书签
            ScrollView {
                visible: reader.drawerTab === "marks"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ColumnLayout {
                    width: drawer.width
                    spacing: 6

                    Text {
                        Layout.margins: 12
                        visible: reader.store.annotations.length === 0 && reader.store.bookmarks.length === 0
                        text: "本章暂无标注。\n\n阅读时选中正文：\n● 三色高亮\n● 写批注\n● 灵感直通创作笔记\n\n顶部「🔖」可加书签。"
                        color: reader.th.faint
                        font.family: Theme.uiFont; font.pixelSize: 11
                        lineHeight: 1.6
                    }

                    Repeater {
                        model: reader.store.annotations
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            Layout.margins: 10
                            Layout.fillWidth: true
                            height: markCol.implicitHeight + 16
                            radius: 10
                            color: Qt.rgba(0.5, 0.5, 0.5, 0.07)
                            border.width: 1
                            border.color: reader.th.border
                            ColumnLayout {
                                id: markCol
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 3
                                RowLayout {
                                    spacing: 6
                                    Rectangle {
                                        width: 8; height: 8; radius: 4
                                        color: modelData.kind === "highlight_yellow" ? reader.th.hlY
                                             : modelData.kind === "highlight_green" ? reader.th.hlG
                                             : modelData.kind === "highlight_red" ? reader.th.hlR
                                             : reader.th.accent
                                    }
                                    Text {
                                        text: modelData.kind === "comment" ? "批注 · " + modelData.ts : "高亮 · " + modelData.ts
                                        color: reader.th.faint
                                        font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        text: "×"
                                        color: reader.th.faint
                                        font.pixelSize: 13
                                        MouseArea {
                                            anchors.fill: parent; anchors.margins: -6
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                bridge.removeAnnotation(reader.curNum, index)
                                                reader.refreshStore()
                                            }
                                        }
                                    }
                                }
                                Text {
                                    visible: modelData.kind !== "comment"
                                    text: modelData.quote
                                    color: reader.th.text
                                    font.family: Theme.serifFont; font.pixelSize: 12
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Text {
                                    visible: modelData.kind === "comment"
                                    text: modelData.note !== "" ? modelData.note : "（点击输入框位置查看）"
                                    color: reader.th.dim
                                    font.family: Theme.uiFont; font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: reader.jumpToRatio(modelData.pos || 0)
                            }
                        }
                    }

                    Repeater {
                        model: reader.store.bookmarks
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            Layout.margins: 10
                            Layout.fillWidth: true
                            height: 40
                            radius: 10
                            color: Qt.rgba(0.89, 0.70, 0.36, 0.08)
                            border.width: 1
                            border.color: reader.th.border
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8
                                Text { text: "🔖"; color: reader.th.accent; font.pixelSize: 13 }
                                Text {
                                    text: modelData.label
                                    color: reader.th.text
                                    font.family: Theme.uiFont; font.pixelSize: 12
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: Math.round((modelData.pos || 0) * 100) + "%"
                                    color: reader.th.faint
                                    font.family: Theme.monoFont; font.pixelSize: Theme.fsMicro
                                }
                                Text {
                                    text: "×"
                                    color: reader.th.faint; font.pixelSize: 13
                                    MouseArea {
                                        anchors.fill: parent; anchors.margins: -6
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            bridge.removeBookmark(reader.curNum, index)
                                            reader.refreshStore()
                                        }
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: reader.jumpToRatio(modelData.pos || 0)
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }

    // ---- 排版设置面板（Aa）----
    Rectangle {
        id: prefsPanel
        visible: false
        anchors.top: topBar.bottom
        anchors.topMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: 12
        width: 300
        height: prefsCol.implicitHeight + 28
        radius: 14
        color: th.card
        border.width: 1
        border.color: th.border
        z: 45

        ColumnLayout {
            id: prefsCol
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Text {
                text: "阅读排版"
                color: reader.th.text
                font.family: Theme.serifFont; font.pixelSize: 14; font.bold: true
            }

            RSegLabel { text: "主题" }
            RSegment {
                Layout.fillWidth: true
                options: ["夜间", "羊皮纸", "纯白"]
                values: ["night", "parchment", "white"]
                current: reader.prefs.theme || "night"
                onPicked: function (v) { reader.prefs.theme = v; bridge.setReaderPref("theme", v) }
            }
            RSegLabel { text: "字号" }
            RSegment {
                Layout.fillWidth: true
                options: ["小", "标准", "大", "特大", "超大"]
                values: [0.85, 1.0, 1.15, 1.35, 1.6]
                current: reader.prefs.fontScale || 1.0
                onPicked: function (v) { reader.prefs.fontScale = v; bridge.setReaderPref("fontScale", v) }
            }
            RSegLabel { text: "行距" }
            RSegment {
                Layout.fillWidth: true
                options: ["紧凑", "标准", "宽松"]
                values: [1.5, 1.8, 2.2]
                current: reader.prefs.lineHeight || 1.8
                onPicked: function (v) { reader.prefs.lineHeight = v; bridge.setReaderPref("lineHeight", v) }
            }
            RSegLabel { text: "字体" }
            RSegment {
                Layout.fillWidth: true
                options: ["宋体", "黑体"]
                values: [true, false]
                current: reader.prefs.serif !== false
                onPicked: function (v) { reader.prefs.serif = v; bridge.setReaderPref("serif", v) }
            }
            RSegLabel { text: "翻页方式" }
            RSegment {
                Layout.fillWidth: true
                options: ["滚动", "左右翻页"]
                values: [false, true]
                current: !!reader.prefs.paged
                onPicked: function (v) { reader.prefs.paged = v; bridge.setReaderPref("paged", v) }
            }
        }
    }

    // ---- 内部小组件 ----

    component RToolButton: Rectangle {
        id: rb
        property string icon: ""
        property string label: ""
        property string tip: ""
        property bool accent: false
        property bool active: false
        property bool dimmed: false
        signal clicked()
        height: 30
        radius: 6
        width: row2.implicitWidth + 16
        opacity: dimmed ? 0.4 : 1
        color: active ? Qt.rgba(0.6, 0.6, 0.6, 0.18)
             : rbMa.containsMouse ? Qt.rgba(0.6, 0.6, 0.6, 0.12) : "transparent"
        Row {
            id: row2
            anchors.centerIn: parent
            spacing: 5
            AppIcon {
                name: rb.icon
                size: 15
                stroke: 1.5
                color: rb.accent ? reader.th.accent
                     : rb.active ? reader.th.text : reader.th.dim
            }
            Text {
                visible: rb.label !== ""
                text: rb.label
                color: rb.accent ? reader.th.accent : reader.th.text
                font.family: Theme.uiFont; font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        MouseArea {
            id: rbMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            enabled: !rb.dimmed
            onClicked: rb.clicked()
        }
        ToolTip.visible: rb.tip !== "" && rbMa.containsMouse
        ToolTip.text: rb.tip
    }

    component RMiniText: Text {
        signal clicked()
        font.family: Theme.uiFont
        font.pixelSize: 12
        anchors.verticalCenter: parent.verticalCenter
        MouseArea {
            anchors.fill: parent; anchors.margins: -6
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }
    }

    component RTabBtn: Rectangle {
        property string text: ""
        property bool active: false
        signal clicked()
        height: 30; radius: 8
        width: tabText.implicitWidth + 22
        color: active ? Qt.rgba(0.89, 0.70, 0.36, 0.16) : "transparent"
        Text {
            id: tabText
            anchors.centerIn: parent
            text: parent.text
            color: active ? reader.th.accent : reader.th.dim
            font.family: Theme.uiFont; font.pixelSize: 12
            font.bold: active
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }

    component RSegLabel: Text {
        text: ""
        color: reader.th.faint
        font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro
    }

    component RSegment: Row {
        id: seg
        property var options: []
        property var values: []
        property var current: null
        signal picked(var value)
        spacing: 5
        layoutDirection: seg.options.length >= 5 ? Qt.LeftToRight : Qt.LeftToRight

        Repeater {
            model: seg.options.length
            Rectangle {
                required property int index
                property var value: seg.values[index]
                height: 27
                radius: 7
                width: segText.implicitWidth + 14
                color: seg.current === value ? reader.th.accent : Qt.rgba(0.5, 0.5, 0.5, 0.1)
                border.width: 1
                border.color: seg.current === value ? reader.th.accent : reader.th.border
                Text {
                    id: segText
                    anchors.centerIn: parent
                    text: seg.options[index]
                    color: seg.current === value ? (reader.prefs.theme === "night" ? "#1D1B17" : "#FFFFFF") : reader.th.dim
                    font.family: Theme.uiFont; font.pixelSize: 11
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: seg.picked(seg.values[index])
                }
            }
        }
    }
}
