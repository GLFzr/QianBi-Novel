import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import ".."

// ============================================================
// ImportDialog · 外部文档一键导入
// 拆解 → 预览「识别出的部分 → 落到哪个产物」→ 作者确认后才写盘。
// 两条底线在界面上的落点：
//   · 只拆实有：每个部分标出逐字比率 / 引证验真数；对不上原文的默认不勾选，
//     并把原因写在该行上（作者仍可显式勾上，机器不替他做主）。
//   · 未识别出的落点直接列出来，让作者看见 Agent 没有替他编东西。
// ============================================================
Dialog {
    id: dlg
    objectName: "importDialog"
    modal: true
    standardButtons: Dialog.NoButton
    width: Math.min(780, parent ? parent.width * 0.86 : 780)
    height: Math.min(640, parent ? parent.height * 0.84 : 640)
    anchors.centerIn: parent
    padding: 18
    background: DialogBg {}

    property var rows: []
    property var sum: ({ items: 0, trusted: 0, untrusted: 0, checked: 0,
                         chars: 0, sourceChars: 0, missing: [] })
    property string report: ""
    property string reportKind: ""
    property int expanded: -1

    function refresh() {
        rows = bridge.importItems()
        sum = bridge.importSummary()
    }
    function openPicker() {
        report = ""
        expanded = -1
        fileDlg.open()
    }
    function evidenceText(md) {
        if (md.verbatim >= 0)
            return "逐字比对 " + md.verbatim + "%"
        if (md.quotesTotal > 0)
            return "引证验真 " + md.quotesOk + "/" + md.quotesTotal
        return "无凭据"
    }

    FileDialog {
        id: fileDlg
        objectName: "importFileDialog"
        title: "选择要导入的文档"
        nameFilters: ["文本文档 (*.txt *.md)", "所有文件 (*)"]
        onAccepted: bridge.startImportDocument(selectedFile.toString())
    }

    header: Column {
        padding: 16
        spacing: 2
        Text {
            text: "导入外部文档"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
        }
        Text {
            text: "Agent 只摘录文档里真实写过的内容 · 拆出的每个部分先给你过一遍，勾选后才写入 · 已有章节一律不覆盖"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.Wrap
            width: parent.width
        }
    }

    contentItem: ColumnLayout {
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            AppButton {
                objectName: "importPickBtn"
                text: bridge.importSourceName === "" ? "选择文档…" : "换个文件…"
                kind: "primary"
                enabled: !bridge.isImporting && !bridge.isRunning
                onClicked: dlg.openPicker()
            }
            Text {
                objectName: "importStageText"
                Layout.fillWidth: true
                text: bridge.isImporting
                      ? (bridge.importStageText || "拆解中…")
                      : (bridge.importSourceName === ""
                         ? "支持 txt / md，编码自动识别（utf-8 / gb18030 / utf-16 / big5）"
                         : bridge.importSourceName + " · 共 " + dlg.sum.sourceChars + " 字")
                color: bridge.isImporting ? Theme.accent : Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideMiddle
            }
            AppButton {
                text: "取消解析"
                kind: "ghost"
                visible: bridge.isImporting
                onClicked: bridge.cancelImport()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: dlg.report !== ""
            radius: Theme.rBtn
            height: reportCol.implicitHeight + 16
            color: dlg.reportKind === "ok" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
                                           : Qt.rgba(0.898, 0.325, 0.294, 0.12)
            border.width: 1
            border.color: dlg.reportKind === "ok" ? Theme.accent : Theme.danger
            ColumnLayout {
                id: reportCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 8
                spacing: 2
                Text {
                    objectName: "importReportTitle"
                    text: dlg.reportKind === "ok" ? "导入完成" : "未能导入"
                    color: dlg.reportKind === "ok" ? Theme.accent : Theme.danger
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.bold: true
                }
                Text {
                    objectName: "importReportText"
                    Layout.fillWidth: true
                    text: dlg.report
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                    wrapMode: Text.Wrap
                }
            }
        }

        Text {
            objectName: "importSummaryText"
            Layout.fillWidth: true
            visible: !bridge.isImporting && dlg.rows.length > 0
            text: "识别出 " + dlg.sum.items + " 个部分（已验真 " + dlg.sum.trusted
                  + (dlg.sum.untrusted > 0 ? " · 未验真 " + dlg.sum.untrusted + "，默认不勾选" : "")
                  + "）· 勾选 " + dlg.sum.checked + " 项，约 " + dlg.sum.chars + " 字"
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            wrapMode: Text.Wrap
        }
        Text {
            objectName: "importMissingText"
            Layout.fillWidth: true
            visible: !bridge.isImporting && dlg.sum.missing.length > 0
            text: "文档里没有这些部分，未凭空生成：" + dlg.sum.missing.join("、")
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.Wrap
        }
        Text {
            objectName: "importEmptyHint"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !bridge.isImporting && dlg.rows.length === 0
            text: dlg.report === ""
                  ? "（还没有解析结果——选一份文档，Agent 会把里面真实存在的部分摘出来给你过目）"
                  : ""
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
        }

        ScrollView {
            objectName: "importListScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: dlg.rows.length > 0
            clip: true
            contentWidth: availableWidth

            ListView {
                objectName: "importRuleList"
                model: dlg.rows
                spacing: 8
                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    id: rowRect
                    objectName: "importRow"
                    required property var modelData
                    width: ListView.view.width
                    height: rowCol.implicitHeight + 18
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: modelData.trust ? Theme.border : Theme.danger

                    ColumnLayout {
                        id: rowCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 9
                        spacing: 3

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            AppCheck {
                                objectName: "importRowCheck"
                                text: rowRect.modelData.label
                                      + (rowRect.modelData.num > 0 ? " 第" + rowRect.modelData.num + "章" : "")
                                font.pixelSize: Theme.fsSmall
                                font.bold: true
                                palette.text: Theme.textPrimary
                                checked: rowRect.modelData.checked
                                onToggled: {
                                    bridge.setImportChecked(rowRect.modelData.index, checked)
                                    dlg.sum = bridge.importSummary()
                                }
                            }
                            Rectangle {
                                visible: rowRect.modelData.suggested || rowRect.modelData.canon !== ""
                                Layout.preferredWidth: tagText.implicitWidth + 12
                                Layout.alignment: Qt.AlignVCenter
                                height: 20
                                radius: 5
                                color: "transparent"
                                border.width: 1
                                border.color: Theme.info
                                Text {
                                    id: tagText
                                    anchors.centerIn: parent
                                    objectName: "importTag"
                                    text: rowRect.modelData.suggested
                                          ? "千笔建议"
                                          : "原作《" + rowRect.modelData.canon + "》"
                                    color: Theme.info
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsTiny
                                }
                            }
                            Rectangle {
                                Layout.preferredWidth: evText.implicitWidth + 12
                                Layout.alignment: Qt.AlignVCenter
                                height: 20
                                radius: 5
                                color: rowRect.modelData.trust
                                       ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.15)
                                       : Qt.rgba(0.898, 0.325, 0.294, 0.16)
                                Text {
                                    id: evText
                                    objectName: "importEvidence"
                                    anchors.centerIn: parent
                                    text: dlg.evidenceText(rowRect.modelData)
                                    color: rowRect.modelData.trust ? Theme.accent : Theme.danger
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsTiny
                                }
                            }
                            Text {
                                text: rowRect.modelData.chars + " 字"
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                            }
                            Item { Layout.fillWidth: true }
                            AppButton {
                                objectName: "importExpandBtn"
                                text: dlg.expanded === rowRect.modelData.index ? "收起" : "看内容"
                                kind: "ghost"
                                height: 22
                                onClicked: dlg.expanded = (dlg.expanded === rowRect.modelData.index
                                                           ? -1 : rowRect.modelData.index)
                            }
                        }

                        Text {
                            objectName: "importTarget"
                            Layout.fillWidth: true
                            text: "→ " + rowRect.modelData.target
                                  + (rowRect.modelData.exists
                                     ? "　（目标已有内容：章级文件跳过不覆盖，设定类只追加）" : "")
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                        }
                        Text {
                            objectName: "importReason"
                            Layout.fillWidth: true
                            visible: !rowRect.modelData.trust && rowRect.modelData.reason !== ""
                            text: "未验真：" + rowRect.modelData.reason + "——勾上即按你的判断导入"
                            color: Theme.danger
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: dlg.expanded !== rowRect.modelData.index
                                     && rowRect.modelData.preview !== ""
                            text: rowRect.modelData.preview
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            visible: dlg.expanded === rowRect.modelData.index
                            Layout.preferredHeight: 200
                            radius: Theme.rBtn
                            color: Theme.bgLog
                            border.width: 1
                            border.color: Theme.border
                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 6
                                TextArea {
                                    readOnly: true
                                    text: dlg.expanded === rowRect.modelData.index
                                          ? bridge.importItemContent(rowRect.modelData.index) : ""
                                    color: Theme.textSecondary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsTiny
                                    wrapMode: Text.Wrap
                                    background: Rectangle { color: "transparent" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    footer: Row {
        spacing: 8
        anchors.right: parent.right
        anchors.margins: 12
        AppButton {
            text: "全选"
            kind: "ghost"
            enabled: dlg.rows.length > 0 && !bridge.isImporting
            onClicked: bridge.setImportAllChecked(true)
        }
        AppButton {
            text: "全不选"
            kind: "ghost"
            enabled: dlg.rows.length > 0 && !bridge.isImporting
            onClicked: bridge.setImportAllChecked(false)
        }
        AppButton {
            text: "关闭"
            kind: "ghost"
            enabled: !bridge.isImporting
            onClicked: dlg.close()
        }
        AppButton {
            objectName: "importConfirmBtn"
            text: "确认导入（" + dlg.sum.checked + "）"
            kind: "primary"
            enabled: !bridge.isImporting && dlg.sum.checked > 0
            onClicked: bridge.confirmImport()
        }
    }

    Connections {
        target: bridge
        function onImportPlanChanged() { dlg.refresh() }
        function onImportResult(ok, text) {
            dlg.reportKind = ok ? "ok" : "err"
            dlg.report = text
            dlg.refresh()
        }
    }

    onOpened: dlg.refresh()
}
