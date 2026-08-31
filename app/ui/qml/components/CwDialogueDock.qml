import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// CwDialogueDock · 共写对话区（M1）
// 每阶段：与对应子 Agent 讨论 → 点「✓确定」总结定稿 / 「↩打回」重议；
// cw_unit / cw_prose 阶段另有「回看世界书」软切入口。
// run_mode=='cw'：发送 → bridge.submitCwMessage；流式回复经 bridge.cwStreamingText 展示。
// ============================================================
Rectangle {
    id: cwDock
    objectName: "cwDialogueDock"
    color: Theme.bgPanel

    property bool viewIsCurrent: bridge.cwViewStage === bridge.cwStageKey
    property bool busy: bridge.cwBusy
    property bool rollbackOpen: false   // 打回目标选择展开（#5 跨阶段打回）

    function send() {
        var t = cwInput.text.trim()
        if (t === "") return
        cwInput.text = ""
        bridge.submitCwMessage(t)
        msgList.positionViewAtEnd()
    }

    function toggleRollback() {
        rollbackOpen = !rollbackOpen
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- 头部：Agent + 阶段 ----
        Rectangle {
            Layout.fillWidth: true
            height: 46
            color: Theme.bgCard
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            Column {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Text {
                    text: bridge.cwAgent + " · " + bridge.cwStageLabel
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.bold: true
                }
                Text {
                    text: cwDock.viewIsCurrent
                          ? (bridge.cwSummary.reopening ? "回看世界书修订中：确定后写回并返回原阶段" : "当前阶段讨论中")
                          : "回看历史阶段（只读，点当前阶段卡片返回）"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
            }
        }

        // ---- GateBanner：✓确定 / ↩打回 / 回看世界书 ----
        Rectangle {
            Layout.fillWidth: true
            height: 44
            color: Theme.bgLog
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6
                AppButton {
                    text: "✓ 确定"
                    kind: "primary"
                    height: 28
                    enabled: cwDock.viewIsCurrent && !cwDock.busy
                    onClicked: bridge.confirmCwStage()
                    ToolTip.visible: hovered
                    ToolTip.text: "把当前阶段已收敛的讨论总结定稿，状态机前进"
                }
                AppButton {
                    text: "↩ 打回"
                    kind: "danger"
                    height: 28
                    visible: bridge.cwSummary.rollbackable
                    enabled: cwDock.viewIsCurrent && !cwDock.busy && bridge.cwSummary.rollbackable
                    onClicked: cwDock.toggleRollback()
                    ToolTip.visible: hovered
                    ToolTip.text: "选择要打回的阶段（当前/历史），级联失效下游产物并归档"
                }
                AppButton {
                    text: "回看世界书"
                    kind: "ghost"
                    height: 28
                    visible: cwDock.viewIsCurrent && bridge.cwSummary.canReopen
                    onClicked: bridge.reopenCwWorldbook()
                    ToolTip.visible: hovered
                    ToolTip.text: "软切回世界书阶段修订（不级联删除），确定后写回并返回"
                }
                AppButton {
                    text: "校验细纲"
                    kind: "ghost"
                    height: 28
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey === "cw_unit" && bridge.cwUnitHasOutlines
                    enabled: !cwDock.busy
                    onClicked: bridge.validateCwOutlines()
                    ToolTip.visible: hovered
                    ToolTip.text: "确定细纲：Agent 重读校验衔接/世界书/正则/单元范围；无阻塞自动进入正文写作"
                }
                AppButton {
                    text: "去AI味"
                    kind: "ghost"
                    height: 28
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey === "cw_prose"
                    enabled: !cwDock.busy
                    onClicked: bridge.deslopCwProse()
                    ToolTip.visible: hovered
                    ToolTip.text: "扫描本章正文并去味改写（读编辑器工作副本）——结果进编辑器，点「保存」才落盘"
                }
                AppButton {
                    text: "审校"
                    kind: "ghost"
                    height: 28
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey === "cw_prose"
                    enabled: !cwDock.busy
                    onClicked: bridge.reviewCwProse()
                    ToolTip.visible: hovered
                    ToolTip.text: "六维审校本章正文（读编辑器工作副本）——问题登记待修汇总，可一键修复"
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: cwDock.busy
                    text: "AI 回复中… 已等待 " + bridge.cwBusySeconds + " 秒"
                    color: Theme.accent
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    SequentialAnimation on opacity {
                        running: cwDock.busy
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: 600 }
                        NumberAnimation { to: 1; duration: 600 }
                    }
                }
                AppButton {
                    text: "取消"
                    kind: "ghost"
                    height: 26
                    visible: cwDock.busy
                    onClicked: bridge.cancelCwWorker()
                    ToolTip.visible: hovered
                    ToolTip.text: "取消在途请求（结果将被丢弃）"
                }
            }
        }

        // ---- 打回目标选择（#5：跨阶段打回）----
        Rectangle {
            Layout.fillWidth: true
            visible: cwDock.rollbackOpen && bridge.cwSummary.rollbackable
            height: 34
            color: Theme.bgLog
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6
                Text {
                    text: "打回到："
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
                Repeater {
                    model: bridge.cwReachedStages
                    delegate: Rectangle {
                        required property var modelData
                        height: 24
                        radius: 6
                        width: rlText.implicitWidth + 14
                        color: rlHot.containsMouse ? Theme.bgHover : Theme.bgCard
                        border.width: 1
                        border.color: Theme.border
                        Text {
                            id: rlText
                            anchors.centerIn: parent
                            text: modelData.label
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        MouseArea {
                            id: rlHot
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                bridge.rollbackCwStageTo(modelData.key)
                                cwDock.rollbackOpen = false
                            }
                        }
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "打回会级联失效下游产物并归档"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
            }
        }

        // ---- 创建项目阶段：题材预设选择（#2）----
        Rectangle {
            Layout.fillWidth: true
            visible: bridge.cwStageKey === "cw_project" && cwDock.viewIsCurrent
            height: 40
            color: Theme.bgLog
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6
                Text {
                    text: "题材预设："
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
                Repeater {
                    model: bridge.genrePresets()
                    delegate: Rectangle {
                        required property var modelData
                        height: 24
                        radius: 6
                        width: pstText.implicitWidth + 14
                        color: bridge.cwPreset === modelData.id
                               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : Theme.bgCard
                        border.width: 1
                        border.color: bridge.cwPreset === modelData.id ? Theme.accent : Theme.border
                        Text {
                            id: pstText
                            anchors.centerIn: parent
                            text: modelData.name
                            color: bridge.cwPreset === modelData.id ? Theme.accent : Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                        MouseArea {
                            id: pstHot
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: bridge.setCwPreset(modelData.id)
                        }
                        ToolTip.visible: pstHot.hovered === true && modelData !== undefined && modelData.description !== ""
                        ToolTip.text: modelData.description
                    }
                }
                Item { Layout.fillWidth: true }
            }
        }

        // ---- 世界书阶段提示（「正则」语义默认逻辑约束规则集，可后改）----
        Rectangle {
            Layout.fillWidth: true
            visible: bridge.cwStageKey === "cw_worldbook" && cwDock.viewIsCurrent
            height: 30
            color: Theme.bgLog
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                text: "「正则」默认=逻辑约束规则集（必须成立的规则清单，每条 level: must/should）——如需字面正则样本，在 设置→写作偏好 切换语义。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        // ---- 单元细纲表单（cw_unit 阶段：定范围/主题，±10 章由批次生成校验）----
        Rectangle {
            Layout.fillWidth: true
            visible: bridge.cwStageKey === "cw_unit" && cwDock.viewIsCurrent
            height: 46
            color: Theme.bgLog
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6
                Text {
                    text: "单元范围"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
                AppSpinBox {
                    id: unitStartBox
                    from: 1; to: 9999; stepSize: 1
                    value: bridge.cwUnitInfo.start > 0 ? bridge.cwUnitInfo.start : 1
                }
                Text {
                    text: "~"
                    color: Theme.textTertiary
                    font.pixelSize: 10
                }
                AppSpinBox {
                    id: unitEndBox
                    from: 1; to: 9999; stepSize: 1
                    value: bridge.cwUnitInfo.target_end > 0 ? bridge.cwUnitInfo.target_end : 1
                }
                TextField {
                    id: unitTopic
                    Layout.fillWidth: true
                    height: 26
                    placeholderText: "单元主题（如：开篇单元·改命初显）"
                    placeholderTextColor: Theme.textTertiary
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    text: bridge.cwUnitInfo.topic !== undefined ? bridge.cwUnitInfo.topic : ""
                    selectByMouse: true
                    background: Rectangle {
                        radius: Theme.rBtn
                        color: Theme.bgHover
                        border.width: 1
                        border.color: unitTopic.activeFocus ? Theme.accent : Theme.border
                    }
                }
                AppButton {
                    text: "登记"
                    height: 26
                    kind: "primary"
                    onClicked: bridge.setCwUnitRange(unitStartBox.value, unitEndBox.value, unitTopic.text)
                    ToolTip.visible: hovered
                    ToolTip.text: "登记单元范围与主题（完结章 ±10 内可浮动），然后点「确定」生成单元总纲与下一批 5 章细纲"
                }
            }
        }

        // ---- 主 Agent 报告区（M5：定稿前衔接比对 / 世界书变更提示；与审校 Findings 分开展示）----
        Rectangle {
            Layout.fillWidth: true
            Layout.margins: 8
            visible: bridge.cwReportText !== ""
            height: 120
            radius: 8
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.info
            clip: true
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 2
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "主 Agent 报告" + (bridge.cwReportTs !== "" ? " · " + bridge.cwReportTs : "")
                        color: Theme.info
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: bridge.cwReportConsumed ? "已派发" : "派给写作 Agent"
                        kind: "ghost"
                        height: 18
                        enabled: !bridge.cwReportConsumed
                        onClicked: bridge.dispatchCwReport()
                        ToolTip.visible: hovered
                        ToolTip.text: bridge.cwReportConsumed
                                      ? "该报告已派发过一次（防重复派单）——新一轮「确定」比对后会有新报告"
                                      : "按报告里的【改写指令】派写作 Agent 改写（不受自动轮次限制；无指令时不可用）"
                    }
                    AppButton {
                        text: "×"
                        kind: "ghost"
                        height: 18
                        onClicked: bridge.clearCwReport()
                    }
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    TextArea {
                        text: bridge.cwReportText
                        readOnly: true
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
            }
        }

        // ---- 消息流（转写）----
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: msgList
                anchors.fill: parent
                clip: true
                spacing: 6
                topMargin: 8
                bottomMargin: 8
                model: bridge.cwMessages
                // 模型整体重建（cwMessages 每次返回新列表）或新增消息后稳定停在底部，
                // 消灭「发送后跳回最上面」；LogView 同款 callLater 模式
                onCountChanged: Qt.callLater(function () { msgList.positionViewAtEnd() })
                onModelChanged: Qt.callLater(function () { msgList.positionViewAtEnd() })
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 4; radius: 2; color: Theme.bgHover }
                }
                delegate: Rectangle {
                    required property var modelData
                    width: msgList.width - 16
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: msgBubble.height + 14
                    radius: 8
                    color: modelData.role === "user" ? Theme.bgActive : Theme.bgCard
                    border.width: 1
                    border.color: Theme.border
                    Column {
                        id: msgBubble
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 7
                        spacing: 3
                        Text {
                            text: modelData.role === "user" ? "你" : bridge.cwAgent
                            color: modelData.role === "user" ? Theme.accent : Theme.info
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: modelData.text
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                            textFormat: Text.PlainText
                        }
                    }
                }
            }
            // 回顶/回底浮动按钮（常显，用户直达）
            Column {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 10
                spacing: 6
                AppButton {
                    text: "▲ 顶部"
                    kind: "ghost"
                    height: 22
                    onClicked: msgList.positionViewAtBeginning()
                }
                AppButton {
                    text: "▼ 底部"
                    kind: "ghost"
                    height: 22
                    onClicked: msgList.positionViewAtEnd()
                }
            }
            Connections {
                target: bridge
                // AI 开始输出：强制回底，让最新消息 + 流式块进入视野
                function onCwBusyChanged() {
                    if (cwDock.busy)
                        Qt.callLater(function () { msgList.positionViewAtEnd() })
                }
                // 流式输出中：仅当已贴近底部才跟随（用户上翻读历史时不被拽回）
                function onCwStreamingChanged() {
                    if (!cwDock.busy) return
                    if (msgList.contentY + msgList.height >= msgList.contentHeight - 60)
                        Qt.callLater(function () { msgList.positionViewAtEnd() })
                }
            }
        }

        // ---- 流式回复缓冲（AI 回复中实时可见）----
        Rectangle {
            Layout.fillWidth: true
            Layout.margins: 8
            visible: cwDock.busy && bridge.cwStreamingText !== ""
            height: 120
            radius: 8
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.accent
            clip: true
            ScrollView {
                anchors.fill: parent
                anchors.margins: 4
                TextArea {
                    text: bridge.cwStreamingText
                    readOnly: true
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                    background: Rectangle { color: "transparent" }
                    onTextChanged: {
                        cursorPosition = text.length
                        Qt.callLater(function () {
                            var fl = parent.parent.flickableItem
                            if (fl) fl.positionViewAtEnd()
                        })
                    }
                }
            }
        }

        // ---- 输入行 ----
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 8
            spacing: 6
            TextField {
                id: cwInput
                Layout.fillWidth: true
                height: 30
                placeholderText: "和 " + bridge.cwAgent + " 讨论这一步…（回车发送）"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                selectByMouse: true
                enabled: cwDock.viewIsCurrent && !cwDock.busy && bridge.cwStageKey !== "cw_project"
                background: Rectangle {
                    radius: Theme.rBtn
                    color: Theme.bgHover
                    border.width: 1
                    border.color: cwInput.activeFocus ? Theme.accent : Theme.border
                }
                Keys.onReturnPressed: cwDock.send()
                Keys.onEnterPressed: cwDock.send()
            }
            AppButton {
                text: "发送"
                kind: "primary"
                height: 30
                enabled: cwInput.enabled && cwInput.text.trim() !== ""
                onClicked: cwDock.send()
            }
        }
    }
}
