import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 章节详情（左右双栏）：左=正文编辑区  右=AI 味扫描结果面板
// ============================================================
ColumnLayout {
    id: detail
    spacing: 0

    signal gotoMonitor()

    function wordCount(t) {
        return t.replace(/\s/g, "").length
    }

    // ---- 顶栏 ----
    Rectangle {
        Layout.fillWidth: true
        height: 56
        color: Theme.bgPanel
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12

            AppButton {
                text: "← 返回流水线"
                kind: "ghost"
                onClicked: detail.gotoMonitor()
            }
            Text {
                text: bridge.chapterPath ? bridge.chapterPath.split(/[\\/]/).pop().replace(".md", "") : "章节详情"
                color: Theme.textPrimary
                font.family: Theme.serifFont
                font.pixelSize: Theme.fsTitle
                font.bold: true
                elide: Text.ElideRight
                Layout.maximumWidth: 400
            }
            Item { Layout.fillWidth: true }
            Text {
                text: editor.text ? "字数：" + detail.wordCount(editor.text) : ""
                color: Theme.textTertiary
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsTiny
            }
            AppButton {
                text: "扫描 AI 味"
                onClicked: bridge.scanChapterText(editor.text)
            }
            AppButton {
                text: "保存"
                kind: "primary"
                onClicked: bridge.saveChapterText(editor.text)
            }
        }
    }

    // ---- 双栏主区 ----
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 0

        // 左：编辑区
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.bgPage
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ScrollView {
                anchors.fill: parent
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                    background: Item {}
                }

                TextArea {
                    id: editor
                    text: bridge.chapterText
                    color: Theme.textPrimary
                    font.family: Theme.serifFont
                    font.pixelSize: 17
                    wrapMode: Text.Wrap
                    selectByMouse: true
                    selectionColor: Theme.accent
                    selectedTextColor: "#1D1B17"
                    leftPadding: 32
                    rightPadding: 32
                    topPadding: 24
                    bottomPadding: 24
                    background: Rectangle { color: Theme.bgPage }
                }
            }
        }

        // 右：扫描结果面板
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: Theme.bgPanel

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "AI 味扫描结果"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        visible: bridge.chapterFindings.length > 0
                        text: bridge.chapterFindings.length + " 处"
                        color: Theme.textTertiary
                        font.family: Theme.monoFont
                        font.pixelSize: Theme.fsTiny
                    }
                }

                // 空状态
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: bridge.chapterFindings.length === 0
                    Column {
                        anchors.centerIn: parent
                        spacing: 8
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "🔍"
                            font.pixelSize: 22
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "点「扫描 AI 味」检查本章\n的 AI 腔句式与毒点"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }

                // 结果列表
                ListView {
                    id: findingsList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: bridge.chapterFindings.length > 0
                    spacing: 4
                    clip: true
                    model: bridge.chapterFindings

                    delegate: Rectangle {
                        width: findingsList.width
                        height: 34
                        radius: 8
                        color: fMouse.containsMouse ? Theme.bgHover : Theme.bgCard
                        border.width: 1
                        border.color: Theme.border

                        Column {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 2
                            Row {
                                spacing: 6
                                Rectangle {
                                    width: 8; height: 8; radius: 4
                                    color: modelData.level === "blocking" ? Theme.danger : Theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.message
                                    color: modelData.level === "blocking" ? Theme.danger : Theme.textPrimary
                                    font.pixelSize: Theme.fsSmall
                                    font.family: Theme.uiFont
                                    font.bold: modelData.level === "blocking"
                                    elide: Text.ElideRight
                                    width: parent.width - 14
                                }
                            }
                            Text {
                                visible: modelData.text !== ""
                                text: "「" + (modelData.text.length > 40 ? modelData.text.substring(0, 40) + "…" : modelData.text) + "」"
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                                elide: Text.ElideRight
                                width: parent.width
                            }
                        }
                        MouseArea {
                            id: fMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                editor.select(modelData.start, modelData.end)
                                editor.forceActiveFocus()
                            }
                        }
                        ToolTip.visible: fMouse.containsMouse && modelData.hint !== ""
                        ToolTip.text: modelData.hint
                    }

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                        background: Item {}
                    }
                }

                // 底部提示
                Text {
                    Layout.fillWidth: true
                    visible: bridge.chapterFindings.length > 0
                    text: "点击条目定位到正文；红色=阻断级，金色=建议级"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
