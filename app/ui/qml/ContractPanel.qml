import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "components"

// ============================================================
// ContractPanel · 本书契约（正则规则集 + 世界书入口）
// 让用户看见 Agent 到底给这本书立了哪些规矩，并能逐条改 / 删。
// 优先级：作者显式指令 > 本书正则 must > 本书世界书 > 细纲 > 预设模板
// 注意「注入 ≠ 执行」：只有带判定式（pattern）的规则能被确定性拦住，
// 自然语言规则靠 prompt 注入 + LLM 审校，是概率性的——界面必须把这条说清。
// ============================================================
Item {
    id: contractPanel
    objectName: "contractPanel"

    property var rows: []
    readonly property int ruleCount: rows ? rows.length : 0
    readonly property int mustCount: {
        var n = 0
        for (var i = 0; rows && i < rows.length; i++) if (rows[i].level === "must") n++
        return n
    }
    property int editing: -1        // 正在编辑的行下标；-1 = 没有
    property string editRule: ""
    property string editLevel: "must"
    property string editScope: ""
    property int pendingDelete: -1  // 二次确认中的行下标

    // 复用「项目文件」编辑器改原文（批量调整时更快）
    signal openProjectFile(string rel)

    function refresh() { rows = bridge.hasProject ? bridge.regexRuleList() : [] }

    function startEdit(i) {
        editing = i
        editRule = rows[i].rule
        editLevel = rows[i].level
        editScope = rows[i].scope
    }

    function commitEdit() {
        if (editing < 0) return
        bridge.updateRegexRule(editing, editRule, editLevel, editScope)
        editing = -1
        refresh()
    }

    function askDelete(i) {
        if (pendingDelete === i) {
            bridge.deleteRegexRule(i)
            pendingDelete = -1
            if (editing === i) editing = -1
            refresh()
        } else {
            pendingDelete = i
        }
    }

    onVisibleChanged: if (visible) refresh()
    Component.onCompleted: refresh()

    Connections {
        target: bridge
        function onRegexRulesChanged() { contractPanel.refresh() }
        function onProjectOpened() {
            contractPanel.editing = -1
            contractPanel.pendingDelete = -1
            contractPanel.refresh()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // ---- 标题 + 说明 + 原文入口 ----
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                Text {
                    text: "本书契约"
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsBig
                    font.bold: true
                }
                Text {
                    text: "生成正文与审校都会带上这些规则；改完自下一次生成起生效，已锁定章节不会自动回改。"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
            AppButton {
                text: "打开规则原文"
                kind: "ghost"
                enabled: bridge.hasProject
                onClicked: contractPanel.openProjectFile("设定/正则.md")
                ToolTip.visible: hovered
                ToolTip.text: "直接编辑 设定/正则.md 原文（适合批量调整）"
            }
            AppButton {
                text: "打开世界书"
                kind: "ghost"
                enabled: bridge.hasProject
                onClicked: contractPanel.openProjectFile("设定/世界书.md")
            }
        }

        Text {
            visible: !bridge.hasProject
            text: "尚未打开书籍。"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
        }

        Text {
            visible: bridge.hasProject && contractPanel.ruleCount > 0
            text: "共 " + contractPanel.ruleCount + " 条 · 其中 "
                  + contractPanel.mustCount + " 条 must（会拦住锁定）"
            color: Theme.textSecondary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
        }

        Text {
            visible: bridge.hasProject && contractPanel.ruleCount === 0
            text: "这本书还没有规则条目。共写档在「世界书」阶段点「确定」，或自动档跑完核心设定后，Agent 会生成一批规则。"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        // ---- 规则列表 ----
        ListView {
            id: ruleList
            objectName: "contractRuleList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: bridge.hasProject
            model: contractPanel.rows
            spacing: 8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
            }

            delegate: Rectangle {
                objectName: "contractRule"
                required property var modelData
                required property int index
                readonly property var d: modelData
                width: ruleList.width
                height: rowCol.implicitHeight + 20
                radius: Theme.rCard
                color: Theme.bgCard
                border.width: 1
                border.color: d.level === "must" ? Theme.border : Theme.bgCard

                ColumnLayout {
                    id: rowCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Rectangle {
                            height: 18
                            width: lvText.implicitWidth + 12
                            radius: 5
                            color: ruleDelegateColor(d.level)
                            Text {
                                id: lvText
                                anchors.centerIn: parent
                                text: d.level === "must" ? "must" : "should"
                                color: d.level === "must" ? Theme.danger : Theme.info
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                                font.bold: true
                            }
                        }
                        Text {
                            text: "范围 " + d.scope
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        Item { Layout.fillWidth: true }
                        AppButton {
                            text: contractPanel.editing === index ? "收起" : "编辑"
                            kind: "ghost"
                            height: 22
                            onClicked: {
                                if (contractPanel.editing === index) contractPanel.editing = -1
                                else contractPanel.startEdit(index)
                            }
                        }
                        AppButton {
                            text: contractPanel.pendingDelete === index ? "确认删除？" : "删除"
                            kind: contractPanel.pendingDelete === index ? "danger" : "ghost"
                            height: 22
                            onClicked: contractPanel.askDelete(index)
                        }
                    }

                    Text {
                        text: d.rule
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: d.pattern !== ""
                        Text {
                            text: "判定式"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        Text {
                            text: "`" + d.pattern + "` · "
                                  + (d.mode === "require" ? "必须有（缺失即提示）" : "不得出现（命中即拦）")
                            color: Theme.info
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }

                    // 管不住告知：判定式坏掉时闸门只会提示不会拦，必须显式说
                    Text {
                        visible: d.broken
                        text: "⚠ 这条判定式无法编译——闸门不会因它阻断，只会作为提示。请修正或删掉。"
                        color: Theme.danger
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Text {
                        visible: d.pattern === ""
                        text: "自然语言规则：靠注入 + AI 审校判定，属概率性约束，不是硬闸门。"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    // ---- 行内编辑 ----
                    ColumnLayout {
                        visible: contractPanel.editing === index
                        Layout.fillWidth: true
                        spacing: 6
                        TextArea {
                            Layout.fillWidth: true
                            text: contractPanel.editRule
                            placeholderText: "规则文本（自然语言，会注入 prompt；反引号内是判定式）"
                            placeholderTextColor: Theme.textTertiary
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            wrapMode: TextArea.Wrap
                            selectByMouse: true
                            onTextChanged: contractPanel.editRule = text
                            background: Rectangle {
                                radius: Theme.rBtn
                                color: Theme.bgHover
                                border.width: 1
                                border.color: Theme.border
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "等级"
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            Repeater {
                                model: [["must", "must（违规拦锁定）"], ["should", "should（只提示）"]]
                                delegate: Rectangle {
                                    required property var modelData
                                    height: 24
                                    width: lvOpt.implicitWidth + 16
                                    radius: 6
                                    color: contractPanel.editLevel === modelData[0]
                                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                           : "transparent"
                                    border.width: 1
                                    border.color: contractPanel.editLevel === modelData[0]
                                                  ? Theme.accent : Theme.border
                                    Text {
                                        id: lvOpt
                                        anchors.centerIn: parent
                                        text: modelData[1]
                                        color: contractPanel.editLevel === modelData[0]
                                               ? Theme.accent : Theme.textTertiary
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: contractPanel.editLevel = modelData[0]
                                    }
                                }
                            }
                            Text {
                                text: "范围"
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            TextField {
                                Layout.preferredWidth: 110
                                text: contractPanel.editScope
                                placeholderText: "全书"
                                placeholderTextColor: Theme.textTertiary
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                selectByMouse: true
                                onTextChanged: contractPanel.editScope = text
                                background: Rectangle {
                                    radius: Theme.rBtn
                                    color: Theme.bgHover
                                    border.width: 1
                                    border.color: Theme.border
                                }
                            }
                            Item { Layout.fillWidth: true }
                            AppButton {
                                text: "保存修改"
                                kind: "primary"
                                height: 24
                                enabled: contractPanel.editRule.trim() !== ""
                                onClicked: contractPanel.commitEdit()
                            }
                        }
                        Text {
                            text: "改动只重写这一条所在的行，其余条目与标题原样保留。"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }
    }

    function ruleDelegateColor(level) {
        return level === "must"
               ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16)
               : Qt.rgba(Theme.info.r, Theme.info.g, Theme.info.b, 0.14)
    }
}
