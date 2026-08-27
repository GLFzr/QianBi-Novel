import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// ============================================================
// 6 维审校问题对话框（v0.13）：A/B/C 三选一
// A: 返上游重做（传染）
// B: 仅本地改稿（不传染）
// C: 忽略通过（标 human）
// ============================================================
Dialog {
    id: reviewDialog
    objectName: "reviewIssueDialog"
    title: "6 维审校问题"
    modal: true
    standardButtons: Dialog.NoButton
    width: Math.min(720, parent.width * 0.85)
    height: Math.min(560, parent.height * 0.85)
    anchors.centerIn: parent
    background: DialogBg {}

    property var issues: []
    property string verdict: ""

    onIssuesChanged: {
        if (issues && issues.length > 0) open()
    }

    contentItem: ColumnLayout {
        spacing: 0

        // 头部
        Rectangle {
            Layout.fillWidth: true
            height: 48
            color: Theme.bgPanel
            radius: Theme.rCard
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 8
                Text {
                    text: "6 维审校问题（" + reviewDialog.issues.length + " 项）"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    Layout.fillWidth: true
                }
                AppBadge {
                    text: reviewDialog.verdict || "REJECT"
                    tint: reviewDialog.verdict === "REJECT-HARD" ? Theme.danger : Theme.accent
                }
            }
        }

        // 问题列表
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: issuesCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ColumnLayout {
                id: issuesCol
                width: parent.width
                spacing: 8
                Item { Layout.preferredHeight: 8 }
                Repeater {
                    model: reviewDialog.issues
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: 12
                        Layout.rightMargin: 12
                        height: issueCol.implicitHeight + 16
                        color: Theme.bgCard
                        radius: Theme.rCard
                        border.width: 1
                        border.color: modelData.level === "fail" ? Theme.danger : Theme.accent
                        ColumnLayout {
                            id: issueCol
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                AppBadge {
                                    text: modelData.dim || "?"
                                    tint: Theme.info
                                }
                                AppBadge {
                                    text: modelData.level || "?"
                                    tint: modelData.level === "fail" ? Theme.danger : Theme.accent
                                }
                                AppBadge {
                                    visible: !!modelData.root_layer
                                    text: modelData.root_layer || ""
                                    tint: Theme.muted
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Text {
                                text: modelData.text || ""
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsSmall
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Text {
                                visible: !!modelData.quote
                                text: "引证：「" + (modelData.quote || "") + "」"
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                                font.italic: true
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
                Item { Layout.preferredHeight: 8 }
            }
        }

        // 底部 3 选 1 按钮
        Rectangle {
            Layout.fillWidth: true
            height: 56
            color: Theme.bgPanel
            radius: Theme.rCard
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                AppButton {
                    text: "A · 返上游重做（传染）"
                    kind: "primary"
                    Layout.fillWidth: true
                    height: 32
                    onClicked: {
                        bridge.resolveReviewIssue("upstream")
                        reviewDialog.close()
                    }
                }
                AppButton {
                    text: "B · 仅本地改稿"
                    kind: "success"
                    Layout.fillWidth: true
                    height: 32
                    onClicked: {
                        bridge.resolveReviewIssue("local")
                        reviewDialog.close()
                    }
                }
                AppButton {
                    text: "C · 忽略通过"
                    Layout.fillWidth: true
                    height: 32
                    onClicked: {
                        bridge.resolveReviewIssue("ignore")
                        reviewDialog.close()
                    }
                }
            }
        }
    }
}
