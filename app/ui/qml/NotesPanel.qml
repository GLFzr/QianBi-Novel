import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 创作笔记（M3）：想法列表（CRUD · 注入范围 · 状态）+ 全局写作偏好
// 人定方向的一切沉淀：阅读灵感、写作中想法、全书文风约束
// ============================================================
Item {
    id: notes

    property var ideas: []
    property string editingId: ""
    property var globalPrefs: ({ stylePref: "", taboos: "", pacePref: "" })

    function refresh() {
        ideas = bridge.ideasList()
        globalPrefs = bridge.writingPrefs()
    }
    Component.onCompleted: refresh()
    Connections {
        target: bridge
        function onIdeaCountChanged() { notes.refresh() }
        function onProjectOpened() { notes.refresh() }
    }

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
                    text: "创作笔记"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                }
                Text {
                    text: bridge.pendingIdeas > 0
                          ? "待注入想法 " + bridge.pendingIdeas + " 条 · 注入下一章/指定章草稿"
                          : "想法 · 灵感 · 全局偏好 —— 人定方向，AI 执行"
                    color: bridge.pendingIdeas > 0 ? Theme.accent : Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
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

                // ---- 新增想法 ----
                Rectangle {
                    Layout.fillWidth: true
                    radius: Theme.rCard
                    color: Theme.bgCard
                    height: newIdeaCol.implicitHeight + 20
                    ColumnLayout {
                        id: newIdeaCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        Text {
                            text: "记一条想法"
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.bold: true
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 56
                            TextArea {
                                id: newIdeaInput
                                width: parent.width
                                placeholderText: "如：下一章让反派先赢一次；女主发现旧照片的秘密；这段感情线慢一点…"
                                placeholderTextColor: Theme.textTertiary
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsSmall
                                wrapMode: Text.Wrap
                                background: Rectangle {
                                    radius: Theme.rBtn
                                    color: Theme.bgHover
                                    border.width: 1
                                    border.color: Theme.border
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "注入范围"
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                            // 范围分段：下一章 / 通用 / 指定章
                            Row {
                                spacing: 4
                                property string scope: "next"
                                id: scopeRow
                                Repeater {
                                    model: [{ t: "下一章", v: "next" }, { t: "通用", v: "通用" }, { t: "指定章", v: "#" }]
                                    delegate: Rectangle {
                                        required property var modelData
                                        height: 24; radius: 6
                                        width: scopeText.implicitWidth + 14
                                        color: (modelData.v === "#" ? scopeRow.scope.indexOf("#") === 0
                                               : scopeRow.scope === modelData.v)
                                              ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                                        border.width: 1
                                        border.color: (modelData.v === "#" ? scopeRow.scope.indexOf("#") === 0
                                                       : scopeRow.scope === modelData.v) ? Theme.accent : Theme.border
                                        Text {
                                            id: scopeText
                                            anchors.centerIn: parent
                                            text: modelData.t
                                            color: (modelData.v === "#" ? scopeRow.scope.indexOf("#") === 0
                                                    : scopeRow.scope === modelData.v) ? Theme.accent : Theme.textTertiary
                                            font.pixelSize: Theme.fsTiny
                                            font.family: Theme.uiFont
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                if (modelData.v === "#") {
                                                    scopeRow.scope = "#" + chapterNoSpin.value
                                                    chapterNoSpin.visible = true
                                                } else {
                                                    scopeRow.scope = modelData.v
                                                    chapterNoSpin.visible = false
                                                }
                                            }
                                        }
                                    }
                                }
                                AppSpinBox {
                                    id: chapterNoSpin
                                    visible: false
                                    from: 1; to: 9999; value: 1
                                    width: 72
                                    height: 24
                                    onValueChanged: if (scopeRow.scope.indexOf("#") === 0) scopeRow.scope = "#" + value
                                }
                            }
                            Item { Layout.fillWidth: true }
                            AppButton {
                                text: "记入笔记"
                                kind: "primary"
                                height: 26
                                onClicked: {
                                    var s = scopeRow.scope
                                    if (s.indexOf("#") === 0) s = s.substring(1)
                                    bridge.submitIdeaScoped(newIdeaInput.text, s)
                                    newIdeaInput.text = ""
                                }
                            }
                        }
                    }
                }

                // ---- 想法列表 ----
                Text {
                    visible: notes.ideas.length > 0
                    text: "想法列表（" + notes.ideas.length + "）"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                }

                Repeater {
                    model: notes.ideas
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        border.width: 1
                        border.color: modelData.status === "pending" ? Theme.border : Theme.border
                        opacity: modelData.status === "applied" ? 0.55 : 1.0
                        height: ideaCol.implicitHeight + 18

                        ColumnLayout {
                            id: ideaCol
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 5

                            RowLayout {
                                spacing: 6
                                Layout.fillWidth: true
                                AppBadge {
                                    text: modelData.status === "pending"
                                          ? (String(modelData.scope) === "next" ? "待应用·下一章"
                                             : String(modelData.scope) === "通用" ? "待应用·通用"
                                             : "待应用·第" + modelData.scope + "章")
                                          : "已应用"
                                    tint: modelData.status === "pending" ? Theme.accent : Theme.success
                                }
                                Text {
                                    text: modelData.ts
                                    color: Theme.textTertiary
                                    font.family: Theme.monoFont
                                    font.pixelSize: 10
                                }
                                Item { Layout.fillWidth: true }
                                // 操作：编辑 / 标记已应用 / 删除
                                AppButton {
                                    text: "编辑"
                                    height: 20
                                    visible: notes.editingId !== modelData.id
                                    onClicked: {
                                        notes.editingId = modelData.id
                                        editIdeaText.text = modelData.text
                                    }
                                }
                                AppButton {
                                    text: "✓"
                                    height: 20
                                    ToolTip.visible: hovered
                                    ToolTip.text: modelData.status === "pending" ? "标记为已应用" : "重新启用（待应用）"
                                    onClicked: {
                                        if (modelData.status === "pending")
                                            bridge.markIdeaApplied(modelData.id)
                                        else
                                            bridge.updateIdea(modelData.id, modelData.text, String(modelData.scope))
                                    }
                                }
                                AppButton {
                                    text: "×"
                                    kind: "danger"
                                    height: 20
                                    onClicked: bridge.removeIdea(modelData.id)
                                }
                            }

                            Text {
                                visible: notes.editingId !== modelData.id
                                Layout.fillWidth: true
                                text: modelData.text
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsSmall
                                wrapMode: Text.Wrap
                            }

                            // 编辑态
                            ColumnLayout {
                                visible: notes.editingId === modelData.id
                                spacing: 6
                                Layout.fillWidth: true
                                TextArea {
                                    id: editIdeaText
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 52
                                    color: Theme.textPrimary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                    background: Rectangle {
                                        radius: Theme.rBtn
                                        color: Theme.bgHover
                                        border.width: 1
                                        border.color: Theme.accent
                                    }
                                }
                                Row {
                                    spacing: 6
                                    layoutDirection: Qt.RightToLeft
                                    Layout.fillWidth: true
                                    AppButton {
                                        text: "保存"
                                        kind: "primary"
                                        height: 24
                                        onClicked: {
                                            bridge.updateIdea(notes.editingId, editIdeaText.text, String(modelData.scope))
                                            notes.editingId = ""
                                        }
                                    }
                                    AppButton {
                                        text: "取消"
                                        height: 24
                                        onClicked: notes.editingId = ""
                                    }
                                }
                            }
                        }
                    }
                }

                // 空状态
                Rectangle {
                    visible: notes.ideas.length === 0
                    Layout.fillWidth: true
                    height: 120
                    radius: Theme.rCard
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.centerIn: parent
                        text: "还没有想法。\n写作中、阅读时（灵感标记）产生的想法都会汇集在这里。"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        horizontalAlignment: Text.AlignHCenter
                        lineHeight: 1.6
                    }
                }

                // ---- 全局写作偏好 ----
                Rectangle {
                    Layout.fillWidth: true
                    radius: Theme.rCard
                    color: Theme.bgCard
                    height: gpCol.implicitHeight + 20
                    ColumnLayout {
                        id: gpCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8
                        Text {
                            text: "全局写作偏好（注入所有章节）"
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.bold: true
                        }
                        Text {
                            text: "作者不改代码就能调全书文风：保存后从下一章开始注入每章正文 prompt。"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        AppField {
                            id: styleField
                            Layout.fillWidth: true
                            label: "文风（例：冷峻克制，短句为主，少形容词）"
                            text: notes.globalPrefs.stylePref || ""
                        }
                        AppField {
                            id: tabooField
                            Layout.fillWidth: true
                            label: "禁忌（例：不写具体品牌；不出现时间具体年份）"
                            text: notes.globalPrefs.taboos || ""
                        }
                        AppField {
                            id: paceField
                            Layout.fillWidth: true
                            label: "节奏（例：三章一个小高潮，每章结尾留钩子）"
                            text: notes.globalPrefs.pacePref || ""
                        }
                        AppButton {
                            text: "保存全局偏好"
                            kind: "primary"
                            height: 28
                            Layout.alignment: Qt.AlignRight
                            onClicked: bridge.saveGlobalPrefs(styleField.text, tabooField.text, paceField.text)
                        }
                    }
                }

                Item { height: 8 }
            }
        }
    }
}
