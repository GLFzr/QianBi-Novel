import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "."
import "components"

// ============================================================
// 预设库面板（v0.13）：独立展示 9 套 v2 题材预设 + 6 阶段 hint 预览
// 顶部 DataTable 列表（已用 ListView+Repeater 实现避免 TreeView 依赖）
// 下方 RichLog 风格预览（按 6 阶段分块）
// ============================================================
Item {
    id: library

    property var presets: []
    property var details: ({})         // id -> details dict
    property string selectedId: ""
    property int selectedIdx: -1

    function refresh() {
        presets = bridge.presetList()
        if (selectedId) {
            var d = {}
            for (var k in details) d[k] = details[k]
            d[selectedId] = bridge.presetDetails(selectedId)
            details = d    // 新对象回赋触发 detailsChanged，预览绑定才会刷新
        }
    }

    function samplingText(d) {
        var s = (d && d.sampling) ? d.sampling : ({})
        var parts = []
        var keys = Object.keys(s)
        for (var i = 0; i < keys.length; i++) parts.push(s[keys[i]].label + "=" + s[keys[i]].value)
        return parts.join(" · ")
    }

    Component.onCompleted: refresh()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // 顶部标题 + 工具栏
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
                    text: "预设库"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                }
                AppBadge {
                    text: presets.length + " 项"
                    tint: Theme.accent
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: "刷新"
                    height: 24
                    onClicked: library.refresh()
                }
                AppButton {
                    text: "导入预设…"
                    kind: "primary"
                    height: 24
                    onClicked: presetFileDlg.open()
                }
            }
        }

        // 主区：纵向叠放 —— 上预设列表 + 下详情预览（适配窄面板坞宽）
        ColumnLayout {
            id: mainCol
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            // 上：预设列表（ListView+Repeater）
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(150, Math.round(mainCol.height * 0.36))
                color: Theme.bgCard
                radius: Theme.rCard
                border.width: 1
                border.color: Theme.border

                ListView {
                    id: presetListView
                    anchors.fill: parent
                    anchors.margins: 1
                    model: library.presets
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: 60
                        color: library.selectedId === modelData.id ? Theme.bgActive
                             : mouseArea.containsMouse ? Theme.bgHover : "transparent"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                        MouseArea {
                            id: mouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                var d = {}
                                for (var k in library.details) d[k] = library.details[k]
                                d[modelData.id] = bridge.presetDetails(modelData.id)
                                library.details = d    // 新对象回赋触发 detailsChanged
                                library.selectedId = modelData.id
                                library.selectedIdx = index
                            }
                        }
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: modelData.name || "（未命名）"
                                    color: Theme.textPrimary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsBody
                                    font.bold: true
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                                AppBadge {
                                    visible: modelData.version >= 2
                                    text: "v" + modelData.version
                                    tint: Theme.success
                                }
                                AppBadge {
                                    visible: modelData.builtin
                                    text: "内置"
                                    tint: Theme.info
                                }
                            }
                            Text {
                                text: modelData.description || ""
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                        }
                    }
                }
            }

            // 下：详情预览
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.bgCard
                radius: Theme.rCard
                border.width: 1
                border.color: Theme.border
                visible: library.selectedId !== ""

                // 顶部按钮行
                Rectangle {
                    id: previewHeader
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 44
                    color: Theme.bgPanel
                    radius: Theme.rCard
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8
                        Text {
                            text: library.details[library.selectedId]
                                  ? (library.details[library.selectedId].name + " · " +
                                     (library.details[library.selectedId].genre || "通用"))
                                  : ""
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsBody
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        AppButton {
                            text: "应用于当前项目"
                            kind: "primary"
                            height: 24
                            enabled: bridge.hasProject && library.selectedId !== ""
                            onClicked: {
                                bridge.setProjectPreset(library.selectedId)
                            }
                        }
                    }
                }

                // 预览区（Flickable + Column 替代 RichLog，避免依赖）
                Flickable {
                    anchors.top: previewHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    contentWidth: width - 20
                    contentHeight: previewCol.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ColumnLayout {
                        id: previewCol
                        width: parent.width - 20
                        spacing: 14
                        // 上 padding
                        Item { Layout.preferredHeight: 10 }
                        // v1 共享字段
                        Repeater {
                            model: library.details[library.selectedId]
                                   ? Object.keys(library.details[library.selectedId].fields)
                                   : []
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: "📋 " + library.details[library.selectedId].fields[modelData].label
                                    color: Theme.textSecondary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    font.bold: true
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: detailText.implicitHeight + 16
                                    color: Theme.bgPage
                                    radius: Theme.rBtn
                                    border.width: 1
                                    border.color: Theme.border
                                    Text {
                                        id: detailText
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        text: library.details[library.selectedId].fields[modelData].value
                                        color: Theme.textPrimary
                                        font.family: Theme.uiFont
                                        font.pixelSize: Theme.fsSmall
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                        // v2 6 阶段 hint
                        Text {
                            text: "✨ 6 阶段特化提示（v2）"
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.bold: true
                        }
                        Repeater {
                            model: library.details[library.selectedId]
                                   ? Object.keys(library.details[library.selectedId].stage_hints)
                                   : []
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: "🎯 " + library.details[library.selectedId].stage_hints[modelData].label
                                    color: Theme.success
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    font.bold: true
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: stageText.implicitHeight + 16
                                    color: Theme.bgPage
                                    radius: Theme.rBtn
                                    border.width: 1
                                    border.color: Theme.border
                                    Text {
                                        id: stageText
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        text: library.details[library.selectedId].stage_hints[modelData].value
                                        color: Theme.textPrimary
                                        font.family: Theme.uiFont
                                        font.pixelSize: Theme.fsTiny
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                        // P1 全书采样基线（不分相位打底；阶段档压在它之上，显式实参压过两者）
                        Text {
                            Layout.fillWidth: true
                            readonly property string base: library.details[library.selectedId]
                                                           ? library.samplingText(library.details[library.selectedId]) : ""
                            visible: base !== ""
                            text: "🧭 全书采样基线：" + base
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            wrapMode: Text.Wrap
                        }
                        // P1 阶段参数档（槽位/采样；审校温度由内核锁死，预设改不动）
                        Text {
                            text: "⚙ 阶段参数档"
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.bold: true
                            visible: library.details[library.selectedId]
                                     ? Object.keys(library.details[library.selectedId].stage_params).length > 0
                                     : false
                        }
                        Repeater {
                            model: library.details[library.selectedId]
                                   ? Object.keys(library.details[library.selectedId].stage_params)
                                   : []
                            delegate: Text {
                                Layout.fillWidth: true
                                text: "· " + library.details[library.selectedId].stage_params[modelData].label
                                      + "：" + library.details[library.selectedId].stage_params[modelData].value
                                      + (modelData === "review" ? "（温度锁 0.2，预设不改）" : "")
                                color: Theme.textSecondary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                                wrapMode: Text.Wrap
                            }
                        }
                        // 底部 padding
                        Item { Layout.preferredHeight: 20 }
                    }
                }
            }

            // 空状态
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.bgCard
                radius: Theme.rCard
                border.width: 1
                border.color: Theme.border
                visible: library.selectedId === ""
                Text {
                    anchors.centerIn: parent
                    text: "↑ 上方列表选一个预设查看详情"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsBody
                }
            }
        }
    }

    // 导入文件对话框
    FileDialog {
        id: presetFileDlg
        objectName: "presetFileDlg"
        title: "选择预设文件（JSON）"
        nameFilters: ["预设文件 (*.json)"]
        onAccepted: {
            var r = bridge.importGenrePreset(selectedFile.toString())
            if (r && r.ok) library.refresh()
        }
    }
}
