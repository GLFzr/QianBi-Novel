import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "."
import "components"

// 书架面板：项目列表 + 新建/打开
Item {
    id: shelf

    property var items: []

    function refresh() {
        items = bridge.recentProjects()
    }
    Component.onCompleted: refresh()
    onVisibleChanged: if (visible) refresh()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // 头部
        Rectangle {
            Layout.fillWidth: true
            height: 66
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 3
                Text {
                    text: "书架"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                }
                Text {
                    text: shelf.items.length + " 本书"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                }
            }
            AppButton {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: "＋"
                height: 28
                onClicked: newProjectDialog.open()
            }
        }

        // 项目列表
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: shelf.items
            spacing: 6
            clip: true
            anchors.margins: 10

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: ListView.view.width - 20
                height: 62
                radius: Theme.rCard
                color: itemHover.containsMouse ? Theme.bgHover : Theme.bgCard
                border.width: 1
                border.color: itemHover.containsMouse ? Theme.borderStrong : Theme.border
                Rectangle { anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; height: 1
                           color: Theme.cardHighlight }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    Rectangle {
                        width: 40; height: 40; radius: 8
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.15)
                        Text {
                            anchors.centerIn: parent
                            text: modelData.name.length > 0 ? modelData.name.charAt(0) : "书"
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: 18
                            font.bold: true
                        }
                    }
                    Column {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            width: parent.width
                            text: modelData.name
                            color: Theme.textPrimary
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.uiFont
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            text: (modelData.genre || "未设题材") + " · " + modelData.chapters + " 章 · " + (modelData.words / 10000).toFixed(1) + " 万字"
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }
                    }
                    Text {
                        visible: itemHover.containsMouse
                        text: "进入 →"
                        color: Theme.accent
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.uiFont
                    }
                }
                MouseArea {
                    id: itemHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bridge.openProject(modelData.path)
                }
            }

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                background: Item {}
            }
        }

        // 空状态引导（新用户）
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: shelf.items.length === 0
            Column {
                anchors.centerIn: parent
                spacing: 10
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "▤"
                    color: Theme.borderStrong
                    font.pixelSize: 40
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "书架还空着"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsBody
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "点下方「新建项目」开始你的第一部作品"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
            }
        }

        // 底部操作
        Rectangle {
            Layout.fillWidth: true
            height: 50
            color: Theme.bgPanel
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8
                AppButton {
                    text: "打开项目…"
                    Layout.fillWidth: true
                    onClicked: openFolderDialog.open()
                }
                AppButton {
                    text: "新建项目"
                    kind: "primary"
                    Layout.fillWidth: true
                    onClicked: newProjectDialog.open()
                }
            }
        }
    }

    FolderDialog {
        id: openFolderDialog
        title: "打开写作项目"
        onAccepted: bridge.openProject(selectedFolder.toString())
    }

    Dialog {
        id: newProjectDialog
        objectName: "newProjectDialog"
        parent: Overlay.overlay
        title: "新建项目"
        modal: true
        onOpened: newPresetCombo.model = bridge.genrePresets()   // 新导入/固化的预设不必重启应用
        width: 440
        padding: 18
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
        }
        header: Text {
            text: "新建项目"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 16
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Row {
                spacing: 8
                width: parent.width
                AppField { id: locationField; width: parent.width - 70; label: "保存位置"; text: bridge.defaultBooksRoot() }
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
            Column {
                spacing: 6
                width: parent.width
                Text { text: "题材预设（题材专项约束注入正文/细纲/审校，写作中可随时切换）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                ComboBox {
                    id: newPresetCombo
                    width: parent.width
                    model: bridge.genrePresets()
                    textRole: "name"
                    font.pixelSize: Theme.fsSmall
                    palette.window: Theme.bgCard
                    palette.text: Theme.textPrimary
                    palette.buttonText: Theme.textPrimary
                    background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                }
            }
            Column {
                spacing: 6
                width: parent.width
                Text { text: "预计总字数（万字）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                AppSpinBox { id: totalWanSpin; width: parent.width; from: 20; to: 2000; stepSize: 10; value: 100 }
            }
            Column {
                spacing: 6
                width: parent.width
                Text { text: "一句话灵感"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                TextArea {
                    id: ideaArea
                    width: parent.width
                    height: 60
                    placeholderText: "主角 + 核心设定 + 爽点方向…"
                    placeholderTextColor: Theme.textTertiary
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsBody
                    wrapMode: Text.Wrap
                    background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
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
                        var m = newPresetCombo.model
                        var it = m && m.get ? m.get(newPresetCombo.currentIndex)
                                            : (m ? m[newPresetCombo.currentIndex] : null)
                        if (bridge.newProject(locationField.text, nameField.text, genreField.text,
                                              platformCombo.currentText, totalWanSpin.value, ideaArea.text,
                                              it ? it.id : "")) {
                            newProjectDialog.close()
                        }
                    }
                }
            }
        }
    }

    // 选择保存位置
    FolderDialog {
        id: locationDialog
        title: "选择保存位置"
        onAccepted: {
            var p = selectedFolder.toString().replace("file:///", "")
            locationField.text = p
        }
    }
}
