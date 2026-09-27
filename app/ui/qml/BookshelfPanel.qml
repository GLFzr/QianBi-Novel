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
                    font.weight: Font.DemiBold
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

        // 项目列表（v1.2 修复：Layout 子项 anchors.margins 无效导致的左贴边右 20px 空隙）
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            leftMargin: 12
            rightMargin: 12
            model: shelf.items
            spacing: 6
            clip: true

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
                height: 62
                radius: Theme.rCard
                color: itemHover.containsMouse ? Theme.bgHover : Theme.bgCard
                border.width: 1
                border.color: itemHover.containsMouse ? Theme.borderStrong : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                // U-20：hover 微浮起（scale 合成器友好，挂 motionOK）
                scale: itemHover.containsMouse && Theme.motionOK ? 1.015 : 1.0
                Behavior on scale { NumberAnimation { duration: Theme.durFast; easing: Theme.easeOut } }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    // 迷你书封：双色调纵向渐变 + 首字
                    Rectangle {
                        width: 40; height: 40; radius: 8
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: Theme.accentSoft }
                            GradientStop { position: 1.0; color: Theme.accentSoft }
                        }
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
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        if (mouse.button === Qt.RightButton) {
                            deleteMenu.bookPath = modelData.path
                            deleteMenu.bookName = modelData.name
                            deleteMenu.popup()
                        } else {
                            bridge.openProject(modelData.path)
                        }
                    }
                }
            }

            ScrollBar.vertical: AppScrollBar {}   // U-20：串联统一滚动条
        }

        // 空状态引导（新用户；v1.2 统一 AppEmptyState + 线性图标，替换裸字符"▤"）
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: shelf.items.length === 0
            AppEmptyState {
                anchors.centerIn: parent
                iconName: "shelf"
                title: "书架还空着"
                hint: "点下方「新建项目」开始你的第一部作品"
                AppButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "先看 5 分钟演示（无需 Key）"
                    kind: "primary"
                    visible: bridge.demoAvailable
                    onClicked: bridge.demoStart()
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
                    id: newProjectButton
                    objectName: "newProjectButton"
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

    // 0.20.1 书架删书：右键菜单（第一步）→ 确认对话框（第二步）
    Menu {
        id: deleteMenu
        objectName: "bookDeleteMenu"
        property string bookPath: ""
        property string bookName: ""
        MenuItem {
            text: "删除…"
            onClicked: {
                deleteDialog.bookPath = deleteMenu.bookPath
                deleteDialog.bookName = deleteMenu.bookName
                var all = bridge.recentProjects()
                for (var i = 0; i < all.length; i++) {
                    if (all[i].path === deleteMenu.bookPath) { deleteDialog.bookInfo = all[i]; break }
                }
                deleteDialog.open()
            }
        }
    }

    Dialog {
        id: deleteDialog
        objectName: "bookDeleteDialog"
        property string bookPath: ""
        property string bookName: ""
        property var bookInfo: null
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
        }
        parent: Overlay.overlay
        modal: true
        width: 480
        padding: 18
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        background: DialogBg {}
        header: Text {
            text: "删除这本书"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.weight: Font.DemiBold
            padding: 16
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                width: parent.width
                text: deleteDialog.bookName
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: deleteDialog.bookPath
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.WrapAnywhere
            }
            Text {
                width: parent.width
                visible: deleteDialog.bookInfo !== null
                text: visible
                     ? "这本书共 " + deleteDialog.bookInfo.chapters + " 章 · "
                       + (deleteDialog.bookInfo.words / 10000).toFixed(1) + " 万字。选择删除方式："
                     : ""
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: "· 仅移出书架：书架列表不再显示，书稿文件原样保留在电脑上。\n· 移入回收站：整个书稿目录移入 Windows 回收站，可在回收站还原（应用永不永久删除）。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
            Row {
                spacing: 8
                anchors.right: parent.right
                AppButton {
                    text: "取消"
                    onClicked: deleteDialog.close()
                }
                AppButton {
                    objectName: "bookDeleteShelfBtn"
                    text: "仅移出书架"
                    onClicked: {
                        bridge.deleteBook(deleteDialog.bookPath, "shelf")
                        deleteDialog.close()
                        shelf.refresh()
                    }
                }
                AppButton {
                    objectName: "bookDeleteDiskBtn"
                    text: "移入回收站"
                    kind: "danger"
                    onClicked: {
                        bridge.deleteBook(deleteDialog.bookPath, "disk")
                        deleteDialog.close()
                        shelf.refresh()
                    }
                }
            }
        }
    }

    Dialog {
        id: newProjectDialog
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
        }
        objectName: "newProjectDialog"
        parent: Overlay.overlay
        title: "新建项目"
        modal: true
        onOpened: {
            newPresetCombo.model = bridge.genrePresets()   // 新导入/固化的预设不必重启应用
            if (bridge.demoActive) bridge.demoStepDone("click_new_project")
        }
        width: 440
        padding: 18
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        background: DialogBg {}   // v1.2：裸 Rectangle → 统一三层投影弹窗底
        header: Text {
            text: "新建项目"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.weight: Font.DemiBold
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
            AppField { id: nameField; objectName: "nameField"; width: parent.width; label: "书名"; placeholder: "如：诡异复苏：我的笔记能改命" }
            Row {
                spacing: 8
                width: parent.width
                AppField { id: genreField; objectName: "genreField"; width: parent.width / 2 - 4; label: "题材"; placeholder: "如：悬疑脑洞" }
                Column {
                    spacing: 6
                    width: parent.width / 2 - 4
                    Text { text: "平台"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                    AppSelect {
                        id: platformCombo
                        width: parent.width
                        model: ["番茄", "起点", "晋江", "七猫", "刺猬猫", "其他"]
                    }
                }
            }
            Column {
                spacing: 6
                width: parent.width
                Text { text: "题材预设（题材专项约束注入正文/细纲/审校，写作中可随时切换）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                AppSelect {
                    id: newPresetCombo
                    objectName: "newPresetCombo"
                    width: parent.width
                    model: bridge.genrePresets()
                    textRole: "name"
                    font.pixelSize: Theme.fsSmall
                }
            }
            Column {
                spacing: 6
                width: parent.width
                Text { text: "预计总字数（万字）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                AppSpinBox { id: totalWanSpin; objectName: "totalWanSpin"; width: parent.width; from: 20; to: 2000; stepSize: 10; value: 100 }
            }
            Column {
                spacing: 6
                width: parent.width
                Text { text: "一句话灵感"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                TextArea {
                    id: ideaArea
                    objectName: "ideaArea"
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
            // ---- 原作世界书（同人档）：酒馆世界书 JSON 直接转条目；纯文本存档等人工拆解 ----
            Column {
                spacing: 6
                width: parent.width
                Text { text: "原作世界书（可选 · 写同人用）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                Row {
                    spacing: 8
                    width: parent.width
                    AppField {
                        id: wbField
                        width: parent.width - 70
                        label: ""
                        placeholder: "选一个 世界书.json / 设定文本，可留空"
                        text: ""
                    }
                    AppButton {
                        text: "选择…"
                        anchors.bottom: parent.bottom
                        onClicked: worldbookDialog.open()
                    }
                }
                Text {
                    width: parent.width
                    text: "SillyTavern 世界书 JSON 会转成世界书条目（蓝灯→常驻、关键词→触发词）；纯文本/Markdown 存进 设定/原作世界书.md，不进 prompt，由你自己拆解。"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsMicro
                    font.family: Theme.uiFont
                    wrapMode: Text.Wrap
                }
            }
            Row {
                spacing: 8
                anchors.right: parent.right
                AppButton { text: "取消"; onClicked: newProjectDialog.close() }
                AppButton {
                    objectName: "createProjectButton"
                    text: "创建并进入"
                    kind: "primary"
                    onClicked: {
                        var m = newPresetCombo.model
                        var it = m && m.get ? m.get(newPresetCombo.currentIndex)
                                            : (m ? m[newPresetCombo.currentIndex] : null)
                        if (bridge.newProject(locationField.text, nameField.text, genreField.text,
                                              platformCombo.currentText, totalWanSpin.value, ideaArea.text,
                                              it ? it.id : "", wbField.text)) {
                            newProjectDialog.close()
                        }
                    }
                }
            }
        }
    }

    // 选择原作世界书文件
    FileDialog {
        id: worldbookDialog
        objectName: "worldbookFileDialog"
        // U-14 复核：FileDialog/FolderDialog 无 enter/exit 属性（compile 抓红），出入场由系统接管
        title: "导入原作世界书"
        nameFilters: ["世界书 / 设定文本 (*.json *.md *.txt)", "所有文件 (*)"]
        onAccepted: {
            wbField.text = selectedFile.toString().replace("file:///", "")
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
