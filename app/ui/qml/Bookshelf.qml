import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "."
import "components"

Item {
    id: shelf

    property var items: []
    property bool ideaBusy: false

    Connections {
        target: bridge
        function onIdeaExpanded(ok, result) {
            shelf.ideaBusy = false
            if (ok) {
                ideaArea.text = result
                bridge.showToast("ok", "选题展开完成，可直接使用或修改")
            } else {
                bridge.showToast("error", "选题展开失败：" + result)
            }
        }
    }

    function refresh() {
        items = bridge.recentProjects()
    }
    Component.onCompleted: refresh()
    onVisibleChanged: if (visible) refresh()

    readonly property var coverPalette: [
        { "top": "#3A2F1C", "bottom": "#14100A", "fg": "#E2B15B" },
        { "top": "#1F2E3A", "bottom": "#0D1418", "fg": "#7FA3C9" },
        { "top": "#33202E", "bottom": "#140D12", "fg": "#C99AC0" },
        { "top": "#1F3329", "bottom": "#0D1410", "fg": "#63C0A8" },
        { "top": "#2E2E1E", "bottom": "#121209", "fg": "#D9C25C" }
    ]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 26
        spacing: 16

        // ---- 顶栏 ----
        RowLayout {
            Layout.fillWidth: true
            Column {
                spacing: 2
                Text {
                    text: "书架"
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: Theme.fsBig
                    font.bold: true
                }
                Text {
                    text: shelf.items.length > 0 ? "共 " + shelf.items.length + " 本书，继续你的创作" : "从一句话灵感开始你的第一本书"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsSmall
                    font.family: Theme.uiFont
                }
            }
            Item { Layout.fillWidth: true }
            AppButton {
                text: "打开项目…"
                onClicked: openFolderDialog.open()
            }
            AppButton {
                text: "＋ 新建项目"
                kind: "primary"
                onClicked: newProjectDialog.open()
            }
        }

        // ---- 项目网格 ----
        GridLayout {
            columns: 3
            columnSpacing: 16
            rowSpacing: 16
            Layout.fillWidth: true

            Repeater {
                model: shelf.items
                delegate: Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 210
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: cardMouse.containsMouse ? Theme.borderStrong : Theme.border
                    Behavior on border.color { ColorAnimation { duration: 120 } }

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        // 封面
                        Rectangle {
                            id: coverRect
                            Layout.fillWidth: true
                            height: 78
                            radius: Theme.rCard
                            readonly property var pal: shelf.coverPalette[index % shelf.coverPalette.length]
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: coverRect.pal.top }
                                GradientStop { position: 1.0; color: coverRect.pal.bottom }
                            }
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: parent.height / 2
                                color: Theme.bgCard
                            }
                            Text {
                                anchors.centerIn: parent
                                text: modelData.name.length > 0 ? modelData.name.charAt(0) : "书"
                                color: coverRect.pal.fg
                                font.family: Theme.serifFont
                                font.pixelSize: 32
                            }
                        }

                        // 信息
                        Column {
                            Layout.fillWidth: true
                            Layout.margins: 14
                            spacing: 4
                            Text {
                                width: parent.width
                                text: modelData.name
                                color: Theme.textPrimary
                                font.pixelSize: 15
                                font.family: Theme.uiFont
                                font.bold: true
                                elide: Text.ElideRight
                            }
                            Text {
                                text: (modelData.genre || "未设题材") + " · " + (modelData.platform || "番茄")
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            Item { height: 4 }
                            Row {
                                width: parent.width
                                Text {
                                    text: modelData.chapters + " 章"
                                    color: Theme.textSecondary
                                    font.pixelSize: Theme.fsTiny
                                    font.family: Theme.monoFont
                                }
                                Item { width: 12 }
                                Text {
                                    text: (modelData.words / 10000).toFixed(1) + " 万字"
                                    color: Theme.textSecondary
                                    font.pixelSize: Theme.fsTiny
                                    font.family: Theme.monoFont
                                }
                            }
                            Item { height: 3 }
                            Text {
                                text: cardMouse.containsMouse ? "进入写作 →" : ""
                                color: Theme.accent
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.uiFont
                            }
                        }
                    }

                    MouseArea {
                        id: cardMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.openProject(modelData.path)
                    }
                }
            }
        }

        // ---- 空状态 ----
        Rectangle {
            visible: shelf.items.length === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.rCard
            color: "transparent"
            border.width: 1
            border.color: Theme.borderStrong

            Column {
                anchors.centerIn: parent
                spacing: 12
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "✍️"
                    font.pixelSize: 34
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "还没有项目"
                    color: Theme.textSecondary
                    font.family: Theme.serifFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "人定主题，AI 写书 —— 输入题材与一句话灵感，自动完成设定、大纲、细纲与正文"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                }
                AppButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "＋ 新建你的第一本书"
                    kind: "primary"
                    onClicked: newProjectDialog.open()
                }
            }
        }

        Item { Layout.fillHeight: true }
    }

    // ---- 打开项目 ----
    FolderDialog {
        id: openFolderDialog
        title: "打开写作项目"
        onAccepted: bridge.openProject(selectedFolder.toString())
    }

    // ---- 新建项目对话框 ----
    Dialog {
        id: newProjectDialog
        title: "新建项目"
        modal: true
        anchors.centerIn: parent
        width: 520
        padding: 0
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgPanel
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: "新建项目"
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 20
        }

        contentItem: Column {
            spacing: 0
            width: 520

            // ---- 第一组：保存与命名 ----
            Rectangle {
                width: parent.width
                height: nameGroupCol.implicitHeight + 36
                color: Theme.bgPage
                Column {
                    id: nameGroupCol
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    Text {
                        text: "保存与命名"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                    Row {
                        spacing: 8
                        width: parent.width
                        AppField {
                            id: locationField
                            width: parent.width - 90
                            label: "保存位置"
                            text: bridge.defaultBooksRoot()
                        }
                        AppButton {
                            text: "选择…"
                            anchors.bottom: parent.bottom
                            onClicked: locationDialog.open()
                        }
                    }
                    AppField { id: nameField; width: parent.width; label: "书名"; placeholder: "如：诡异复苏：我的笔记能改命" }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---- 第二组：创作设定 ----
            Rectangle {
                width: parent.width
                height: ideaGroupCol.implicitHeight + 36
                color: Theme.bgPage
                Column {
                    id: ideaGroupCol
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    Text {
                        text: "创作设定"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                    Row {
                        spacing: 8
                        width: parent.width
                        AppField { id: genreField; width: parent.width / 2 - 4; label: "题材"; placeholder: "如：悬疑脑洞" }
                        Column {
                            spacing: 6
                            width: parent.width / 2 - 4
                            Text { text: "平台"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                            ComboBox {
                                id: platformCombo
                                width: parent.width
                                model: ["番茄", "起点", "晋江", "七猫", "刺猬猫", "其他"]
                                palette.window: Theme.bgCard
                                palette.text: Theme.textPrimary
                                palette.buttonText: Theme.textPrimary
                                background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                            }
                        }
                    }
                    Row {
                        spacing: 8
                        width: parent.width
                        Column {
                            spacing: 6
                            width: parent.width / 2 - 4
                            Text { text: "预计总字数（万字）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                            AppSpinBox {
                                id: totalWanSpin
                                width: parent.width
                                from: 20
                                to: 2000
                                stepSize: 10
                                value: 100
                            }
                        }
                        Item { width: parent.width / 2 - 4; height: 1 }
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---- 第三组：灵感 ----
            Rectangle {
                width: parent.width
                height: inspireCol.implicitHeight + 36
                color: Theme.bgPage
                Column {
                    id: inspireCol
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    Row {
                        width: parent.width
                        Text {
                            text: "一句话灵感"
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }
                        Item { width: 10 }
                        AppButton {
                            text: shelf.ideaBusy ? "展开中…" : "✨ AI 展开"
                            kind: "ghost"
                            height: 22
                            enabled: !shelf.ideaBusy
                            onClicked: { shelf.ideaBusy = true; bridge.expandIdea(ideaArea.text) }
                        }
                        Item { width: 0; height: 1 }
                    }
                    ScrollView {
                        width: parent.width
                        height: 84
                        TextArea {
                            id: ideaArea
                            placeholderText: "主角 + 核心设定 + 爽点方向…"
                            placeholderTextColor: Theme.textTertiary
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsBody
                            wrapMode: Text.Wrap
                            background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        }
                    }
                }
            }

            // ---- 底部按钮 ----
            Rectangle {
                width: parent.width
                height: 56
                color: Theme.bgPanel
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
                Row {
                    spacing: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    AppButton { text: "取消"; onClicked: newProjectDialog.close() }
                    AppButton {
                        text: "创建并进入"
                        kind: "primary"
                        onClicked: {
                            if (bridge.newProject(locationField.text, nameField.text, genreField.text,
                                                  platformCombo.currentText, totalWanSpin.value, ideaArea.text)) {
                                newProjectDialog.close()
                                nameField.text = ""; genreField.text = ""; ideaArea.text = ""
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- 选择保存位置 ----
    FolderDialog {
        id: locationDialog
        title: "选择保存位置"
        onAccepted: {
            var p = selectedFolder.toString().replace("file:///", "")
            locationField.text = p
        }
    }
}
