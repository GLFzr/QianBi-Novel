import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// 章级生成配置快照（P2）：这章到底吃了哪些世界书条目、什么参数
// 内容排版全在 bridge.chapterGenConfig() 里，这里只逐节画出来
// ============================================================
Dialog {
    id: genDialog
    objectName: "genConfigDialog"
    modal: true
    standardButtons: Dialog.NoButton
    width: Math.min(640, parent ? parent.width * 0.85 : 640)
    height: Math.min(540, parent ? parent.height * 0.85 : 540)
    anchors.centerIn: parent
    padding: 0
    background: DialogBg {}

    property int num: 0
    property var sections: []
    property bool hasSnapshot: false

    function showFor(n) {
        genDialog.num = n
        var d = bridge.chapterGenConfig(n)
        genDialog.hasSnapshot = !!(d && d.found)
        if (!genDialog.hasSnapshot) {
            genDialog.sections = [{
                title: "第 " + n + " 章没有生成配置记录",
                lines: ["该章写成本次改造之前，或由手工创建：既无世界书激活清单，也无参数档快照。",
                        "重新生成（重写本章）后即会登记。"]
            }]
        } else {
            genDialog.sections = d.sections
        }
        genDialog.open()
    }

    contentItem: ColumnLayout {
        spacing: 0

        // 头部
        Rectangle {
            Layout.fillWidth: true
            height: 46
            color: Theme.bgPanel
            radius: Theme.rCard
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 8
                Text {
                    text: "第 " + genDialog.num + " 章 · 生成配置快照"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    Layout.fillWidth: true
                }
                AppButton {
                    text: "固化为模板"
                    kind: "ghost"
                    height: 26
                    visible: genDialog.hasSnapshot
                    onClicked: bridge.saveChapterPresetTemplate(genDialog.num)
                }
                AppButton {
                    text: "关闭"
                    kind: "ghost"
                    height: 26
                    onClicked: genDialog.close()
                }
            }
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: body.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: body
                objectName: "genConfigBody"
                width: parent.width
                spacing: 10
                Item { Layout.preferredHeight: 6 }
                Repeater {
                    model: genDialog.sections
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: 14
                        Layout.rightMargin: 14
                        spacing: 4

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Rectangle {
                                Layout.preferredWidth: 3
                                Layout.preferredHeight: 12
                                radius: 1
                                color: Theme.accent
                            }
                            Text {
                                text: modelData.title || ""
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsSmall
                                font.bold: true
                                Layout.fillWidth: true
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: Theme.border
                        }

                        Repeater {
                            model: modelData.lines || []
                            delegate: Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData
                                color: Theme.textPrimary
                                font.family: Theme.monoFont
                                font.pixelSize: Theme.fsTiny
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
                Item { Layout.preferredHeight: 6 }
            }
        }
    }
}
