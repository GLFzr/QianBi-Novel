import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

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
                text: "← 返回"
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
                Layout.maximumWidth: 420
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

    // ---- 编辑区 + 扫描结果 ----
    ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.margins: 0
        spacing: 0

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

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

        // 扫描结果面板
        Rectangle {
            Layout.fillWidth: true
            visible: bridge.chapterFindings.length > 0
            height: visible ? Math.min(170, findingsList.contentHeight + 44) : 0
            color: Theme.bgPanel
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

            Column {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6
                Row {
                    spacing: 10
                    Text {
                        text: "AI 味扫描结果（" + bridge.chapterFindings.length + " 处）"
                        color: Theme.textSecondary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                    Text {
                        text: "点击条目定位到正文"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                }
                ListView {
                    id: findingsList
                    width: parent.width
                    height: parent.height - 24
                    spacing: 4
                    clip: true
                    model: bridge.chapterFindings

                    delegate: Rectangle {
                        width: findingsList.width
                        height: 28
                        radius: 6
                        color: fMouse.containsMouse ? Theme.bgHover : "transparent"

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            spacing: 8
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: modelData.level === "blocking" ? Theme.danger : Theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: modelData.message + (modelData.text ? "：「" + (modelData.text.length > 36 ? modelData.text.substring(0, 36) + "…" : modelData.text) + "」" : "")
                                color: modelData.level === "blocking" ? Theme.danger : Theme.accent
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.uiFont
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
                }
            }
        }
    }
}
