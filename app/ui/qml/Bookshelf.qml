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
        { "bg": "#2A2418", "fg": "#E2B15B" },
        { "bg": "#18232A", "fg": "#7FA3C9" },
        { "bg": "#241A20", "fg": "#C99AC0" },
        { "bg": "#1A2418", "fg": "#63C0A8" },
        { "bg": "#20201A", "fg": "#D9C25C" }
    ]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 26
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "书架"
                color: Theme.textPrimary
                font.family: Theme.serifFont
                font.pixelSize: Theme.fsBig
                font.bold: true
            }
            Text {
                text: shelf.items.length + " 个项目"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsSmall
                font.family: Theme.uiFont
                Layout.alignment: Qt.AlignBottom
                Layout.bottomMargin: 3
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

        GridLayout {
            columns: 3
            columnSpacing: 14
            rowSpacing: 14
            Layout.fillWidth: true

            Repeater {
                model: shelf.items
                delegate: Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 226
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: cardMouse.containsMouse ? Theme.borderStrong : Theme.border

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            height: 84
                            radius: Theme.rCard
                            readonly property var pal: shelf.coverPalette[index % shelf.coverPalette.length]
                            color: pal.bg
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: parent.height / 2
                                color: Theme.bgCard
                            }
                            Text {
                                anchors.centerIn: parent
                                text: modelData.name.length > 0 ? modelData.name.charAt(0) : "书"
                                color: parent.pal.fg
                                font.family: Theme.serifFont
                                font.pixelSize: 34
                            }
                        }

                        Column {
                            Layout.fillWidth: true
                            Layout.margins: 14
                            spacing: 6
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
                                Item { width: 14 }
                                Text {
                                    text: (modelData.words / 10000).toFixed(1) + " 万字"
                                    color: Theme.textSecondary
                                    font.pixelSize: Theme.fsTiny
                                    font.family: Theme.monoFont
                                }
                            }
                            Item { height: 2 }
                            Text {
                                text: "进入 →"
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

        Rectangle {
            visible: shelf.items.length === 0
            Layout.fillWidth: true
            height: 120
            radius: Theme.rCard
            color: "transparent"
            border.width: 1
            border.color: Theme.borderStrong
            Text {
                anchors.centerIn: parent
                text: "还没有项目 —— 从一句话灵感开始你的第一本书"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsBody
                font.family: Theme.uiFont
            }
        }

        Item { Layout.fillHeight: true }
    }

    FolderDialog {
        id: openFolderDialog
        title: "打开写作项目"
        onAccepted: bridge.openProject(selectedFolder.toString())
    }

    Dialog {
        id: newProjectDialog
        title: "新建项目"
        modal: true
        anchors.centerIn: parent
        width: 460
        padding: 20
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
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
            spacing: 12
            width: 420

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
            Column {
                spacing: 6
                width: parent.width
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
                    Item { Layout.fillWidth: true }
                }
                ScrollView {
                    width: parent.width
                    height: 90
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
            Row {
                spacing: 8
                anchors.right: parent.right
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

    FolderDialog {
        id: locationDialog
        title: "选择保存位置"
        onAccepted: {
            var p = selectedFolder.toString().replace("file:///", "")
            locationField.text = p
        }
    }
}
