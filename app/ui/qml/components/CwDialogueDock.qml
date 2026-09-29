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
    // 是否跟随新内容钉底。默认关：用户没主动回底就不该被拽走视野（#6）。
    property bool follow: false
    // 回应模式（方案 A）：讨论=确认收敛短回复（默认）；撰写=直接产出草案。
    // 记忆在项目状态里（bridge.cwStageMode），切阶段自动回讨论。
    property bool composeMode: bridge.cwStageMode === "compose"

    onComposeModeChanged: bridge.setCwStageMode(composeMode ? "compose" : "discuss")

    function goToEnd() { msgList.positionViewAtEnd() }

    function send() {
        var t = cwInput.text.trim()
        if (t === "") return
        cwInput.text = ""
        bridge.submitCwMessage(t, composeMode ? "compose" : "discuss")
        cwDock.follow = true      // 刚发的话当然要在眼前
        Qt.callLater(cwDock.goToEnd)
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
                    font.pixelSize: Theme.fsMicro
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
                    objectName: "cwConfirmButton"
                    text: bridge.cwStageKey === "cw_unit" ? "✓ 确定细纲" : "✓ 确定"
                    kind: "primary"
                    height: 28
                    enabled: cwDock.viewIsCurrent && !cwDock.busy
                    onClicked: bridge.confirmCwStage()
                    ToolTip.visible: hovered
                    ToolTip.text: bridge.cwStageKey === "cw_unit"
                                  ? "定稿本单元；已有细纲则重读校验衔接/世界书/正则契约，通过即进入「正文写作」；一批细纲都还没出则先生成第一批"
                                  : "把当前阶段已收敛的讨论总结定稿，进入下一阶段"
                }
                AppButton {
                    text: "↻ 生成下一批"
                    kind: "ghost"
                    height: 28
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey === "cw_unit"
                    enabled: !cwDock.busy
                    onClicked: bridge.generateNextCwOutlines()
                    ToolTip.visible: hovered
                    ToolTip.text: "只往后滚动生成下一批 5 章细纲，阶段不变（要收口本单元请点「确定细纲」）"
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
                // ---- C2/F3：比对失败或结论未收口 → 重试 / 越权锁定（留痕）----
                AppButton {
                    text: "重试比对"
                    kind: "secondary"
                    height: 28
                    visible: (bridge.supervisorFailed || bridge.supervisorAttention)
                             && cwDock.viewIsCurrent && bridge.cwStageKey === "cw_prose"
                    enabled: !cwDock.busy
                    onClicked: bridge.retrySupervisor()
                    ToolTip.visible: hovered
                    ToolTip.text: "重新做定稿前衔接比对"
                }
                AppButton {
                    text: bridge.supervisorFailed ? "跳过比对并锁定" : "无视报告并锁定（留痕）"
                    kind: "danger"
                    height: 28
                    visible: (bridge.supervisorFailed || bridge.supervisorAttention)
                             && cwDock.viewIsCurrent && bridge.cwStageKey === "cw_prose"
                    enabled: !cwDock.busy
                    onClicked: bridge.forceLockChapter()
                    ToolTip.visible: hovered
                    ToolTip.text: bridge.supervisorFailed
                                  ? "比对服务不可用时的出口：直接锁定本章并在状态里留痕（skipped）"
                                  : "作者越权出口：比对结论未收口仍要锁定，状态里留痕（overridden）"
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: cwDock.busy
                    text: "AI 回复中… 已等待 " + bridge.cwBusySeconds + " 秒"
                    color: Theme.accent
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsMicro
                    SequentialAnimation on opacity {
                        running: cwDock.busy && Theme.motionOK
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: Theme.durLoop / 2 }
                        NumberAnimation { to: 1; duration: Theme.durLoop / 2 }
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
                    font.pixelSize: Theme.fsMicro
                }
                Repeater {
                    model: bridge.cwReachedStages
                    delegate: Rectangle {
                        required property var modelData
                        height: 24
                        radius: Theme.rMd
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
                            font.pixelSize: Theme.fsMicro
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
                    font.pixelSize: Theme.fsMicro
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
                    font.pixelSize: Theme.fsMicro
                }
                Repeater {
                    model: bridge.genrePresets()
                    delegate: Rectangle {
                        required property var modelData
                        height: 24
                        radius: Theme.rMd
                        width: pstText.implicitWidth + 14
                        color: bridge.cwPreset === modelData.id
                               ? Theme.accentSoft : Theme.bgCard
                        border.width: 1
                        border.color: bridge.cwPreset === modelData.id ? Theme.accent : Theme.border
                        Text {
                            id: pstText
                            anchors.centerIn: parent
                            text: modelData.name
                            color: bridge.cwPreset === modelData.id ? Theme.accent : Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsMicro
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
                font.pixelSize: Theme.fsMicro
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
                    font.pixelSize: Theme.fsMicro
                }
                AppSpinBox {
                    id: unitStartBox
                    from: 1; to: 9999; stepSize: 1
                    value: bridge.cwUnitInfo.start > 0 ? bridge.cwUnitInfo.start : 1
                }
                Text {
                    text: "~"
                    color: Theme.textTertiary
                    font.pixelSize: Theme.fsMicro
                }
                AppSpinBox {
                    id: unitEndBox
                    from: 1; to: 9999; stepSize: 1
                    // A6：未登记时预填 10——与起始 1 组成 1~10 默认单元（登记后跟随已存值）
                    value: bridge.cwUnitInfo.target_end > 0 ? bridge.cwUnitInfo.target_end : 10
                }
                TextField {
                    id: unitTopic
                    Layout.fillWidth: true
                    height: 26
                    placeholderText: "单元主题（如：开篇单元·改命初显）"
                    placeholderTextColor: Theme.textTertiary
                    color: Theme.textPrimary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsMicro
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
                    ToolTip.text: "登记单元范围与主题（完结章 ±10 内可浮动），然后点「确定细纲」定稿并生成第一批细纲"
                }
            }
        }

        // ---- OB-M1：软开局卡片（示例立项 s1 / 示范讨论 s2 / 交还 hand）----
        // 方案 v1：前 1-2 步由应用代填带「示例」标记的输入并逐字段解释；第一章
        // 写完交还评判。三退出全部落 bridge（cwSoftSkip/SubmitEdited/Hand*），
        // 无 Key 只允许走到卡片为止（bridge 侧 _slot_readiness 前置，零请求）。
        Rectangle {
            id: softCard
            Layout.fillWidth: true
            Layout.margins: 8
            visible: bridge.cwSoft.step !== "" && cwDock.viewIsCurrent
            height: softCardCol.implicitHeight + 20
            radius: 8
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.accent
            clip: true

            property bool editMode: false
            onVisibleChanged: if (visible) editMode = false

            ColumnLayout {
                id: softCardCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 6

                // ---- s1：示例立项（就用这个开写 / 我来改 / 跳过）----
                ColumnLayout {
                    visible: bridge.cwSoft.step === "s1"
                    Layout.fillWidth: true
                    spacing: 5
                    Text {
                        text: "先用这本书试试手：《种子书》同款开局"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "下面四件事已替你填好示例——可以直接开写，也可以改成你自己的。每一步之后仍由你确认。"
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    Repeater {
                        id: softFieldRepeater
                        model: bridge.cwSoft.fields || []
                        delegate: ColumnLayout {
                            required property var modelData
                            required property int index
                            property string val: modelData.value
                            Layout.fillWidth: true
                            spacing: 1
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: modelData.label
                                    color: Theme.info
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    visible: !softCard.editMode
                                    Layout.fillWidth: true
                                    text: modelData.value + (modelData.key === "words" ? " 万字" : "")
                                    color: Theme.textPrimary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                                TextField {
                                    visible: softCard.editMode
                                    Layout.fillWidth: true
                                    text: modelData.value
                                    color: Theme.textPrimary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsSmall
                                    selectByMouse: true
                                    background: Rectangle {
                                        radius: Theme.rBtn
                                        color: Theme.bgHover
                                        border.width: 1
                                        border.color: Theme.accent
                                    }
                                    onTextChanged: {
                                        var it = softFieldRepeater.itemAt(index)
                                        if (it) it.val = text
                                    }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "· " + modelData.note
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsMicro
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        AppButton {
                            text: softCard.editMode ? "就这样开写" : "就用这个开写（会调用模型，产生少量费用）"
                            kind: "primary"
                            onClicked: {
                                if (softCard.editMode) {
                                    var g = "", p = "", w = 100, i2 = ""
                                    for (var k = 0; k < softFieldRepeater.count; k++) {
                                        var it = softFieldRepeater.itemAt(k)
                                        var key = (bridge.cwSoft.fields[k] || {}).key
                                        if (key === "genre") g = it.val
                                        else if (key === "platform") p = it.val
                                        else if (key === "words") w = parseInt(it.val) || 0
                                        else if (key === "idea") i2 = it.val
                                    }
                                    bridge.cwSoftSubmitEdited(g, p, w, i2)
                                } else {
                                    bridge.cwSoftUseExample()
                                }
                            }
                            ToolTip.visible: hovered && !softCard.editMode
                            ToolTip.text: "示例值作为你的输入走真实共写链（与手输同价）；还没有可用连接时只停在卡片，不会发起任何请求"
                        }
                        AppButton {
                            text: softCard.editMode ? "不改了" : "我来改"
                            kind: "ghost"
                            onClicked: softCard.editMode = !softCard.editMode
                            ToolTip.visible: hovered && !softCard.editMode
                            ToolTip.text: "示例值原地可编辑——改完提交即视为你自己的立项（软开局退出）"
                        }
                        AppButton {
                            text: "跳过，我自己说"
                            kind: "ghost"
                            visible: !softCard.editMode
                            onClicked: bridge.cwSoftSkip()
                            ToolTip.visible: hovered
                            ToolTip.text: "收起示例——之后点「✓ 确定」按你创建时填的选题进入核心设定"
                        }
                    }
                }

                // ---- s2：示范一次「讨论」（发送这条 / 改改再发 / 先不用）----
                ColumnLayout {
                    visible: bridge.cwSoft.step === "s2"
                    Layout.fillWidth: true
                    spacing: 5
                    Text {
                        text: "示范一次「讨论」"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "草稿已出。讨论 ≠ 重来——你可以只对局部提要求，比如："
                        color: Theme.textSecondary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rBtn
                        color: Theme.bgHover
                        border.width: 1
                        border.color: Theme.border
                        Text {
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.margins: 8
                            text: "「" + (bridge.cwSoft.exampleReply || "") + "」"
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            font.italic: true
                            wrapMode: Text.Wrap
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        AppButton {
                            text: "发送这条"
                            kind: "primary"
                            onClicked: bridge.cwSoftStep2Send()
                            ToolTip.visible: hovered
                            ToolTip.text: "按真实讨论链发送（会调用模型，与手输同价）——发送后示例全部退场"
                        }
                        AppButton {
                            text: "改改再发"
                            kind: "ghost"
                            onClicked: {
                                cwInput.text = bridge.cwSoft.exampleReply || ""
                                bridge.cwSoftStep2Defer()
                                cwInput.forceActiveFocus()
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: "把这条示例填进输入框，你改成自己的话再发送"
                        }
                        AppButton {
                            text: "先不用"
                            kind: "ghost"
                            onClicked: bridge.cwSoftStep2Defer()
                        }
                    }
                }

                // ---- hand：交还卡片（继续共写 / 我来改 / 换个方向重来）----
                ColumnLayout {
                    visible: bridge.cwSoft.step === "hand"
                    Layout.fillWidth: true
                    spacing: 5
                    Text {
                        text: "第一章完成了——它是怎么长出来的"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Repeater {
                        model: bridge.cwSoft.growth || []
                        delegate: Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: "· " + modelData
                            color: Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: bridge.cwSoft.exportHint || ""
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsMicro
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        AppButton {
                            text: "继续共写"
                            kind: "primary"
                            onClicked: bridge.cwSoftHandContinue()
                            ToolTip.visible: hovered
                            ToolTip.text: "软开局到此收官——此后一切如常"
                        }
                        AppButton {
                            text: "我来改"
                            kind: "ghost"
                            onClicked: bridge.cwSoftHandEdit()
                            ToolTip.visible: hovered
                            ToolTip.text: "解锁本章进编辑器——保存后 Agent 会揣摩你的手改意图"
                        }
                        AppButton {
                            text: "换个方向重来"
                            kind: "danger"
                            onClicked: bridge.cwSoftHandRestart()
                            ToolTip.visible: hovered
                            ToolTip.text: "本章归档（版本历史可回看），打回「核心设定」重新来——软开局不再代填"
                        }
                    }
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
                        font.pixelSize: Theme.fsMicro
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
                        iconName: "close"
                        text: ""
                        kind: "ghost"
                        height: 20
                        onClicked: bridge.clearCwReport()
                        ToolTip.visible: hovered
                        ToolTip.text: "关闭报告"
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
                        font.pixelSize: Theme.fsMicro
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
                objectName: "cwMsgList"
                anchors.fill: parent
                clip: true
                spacing: 6
                topMargin: 8
                bottomMargin: 8
                model: bridge.cwMessageModelProp
                // 只在「已回到底部」时跟随新内容。旧写法是 onCountChanged /
                // onModelChanged 无条件 positionViewAtEnd —— 流式期间每秒都在拽回底部，
                // 用户根本拖不上去。（模型换成增量插行后，onModelChanged 这个坑本身也没了）
                onCountChanged: if (cwDock.follow) Qt.callLater(cwDock.goToEnd)
                // 内容变高时，只要还贴着底部就继续贴着（新消息插进来会瞬时无尾）
                onContentHeightChanged: if (cwDock.follow) Qt.callLater(cwDock.goToEnd)
                // 往上滚（拖动或滚轮）即刻停止跟随；重新贴底则自动恢复跟随
                // （prevContentY 是 Flickable 的 C++ 内部量，QML 取不到，只能自己记）
                property real lastContentY: 0
                onContentYChanged: {
                    if (contentY < lastContentY - 1) cwDock.follow = false
                    lastContentY = contentY
                }
                onAtYEndChanged: if (atYEnd) cwDock.follow = true
                ScrollBar.vertical: AppScrollBar {}
                delegate: Rectangle {
                    id: msgBubbleRect
                    required property string msgRole
                    required property string msgText
                    required property var msgNums
                    readonly property bool batchLink: msgNums && msgNums.length > 0
                    width: msgList.width - 16
                    x: 8
                    height: msgBubble.height + 14
                    radius: 8
                    color: msgRole === "user" ? Theme.bgActive : Theme.bgCard
                    border.width: 1
                    border.color: msgHover.hovered && batchLink ? Theme.accent : Theme.border
                    HoverHandler { id: msgHover }
                    Column {
                        id: msgBubble
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 7
                        spacing: 3
                        Text {
                            text: msgRole === "user" ? "你" : bridge.cwAgent
                            color: msgRole === "user" ? Theme.accent : Theme.info
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsMicro
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: msgText
                            color: Theme.textPrimary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                            textFormat: Text.PlainText
                        }
                        Text {
                            visible: msgBubbleRect.batchLink
                            text: "▸ 点我看这批细纲"
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsMicro
                        }
                    }
                    // 按下即放行给 Flickable，否则 MouseArea 会吃掉拖动（又变成拖不动）
                    MouseArea {
                        anchors.fill: parent
                        propagateComposedEvents: true
                        acceptedButtons: Qt.LeftButton
                        cursorShape: msgBubbleRect.batchLink ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onPressed: mouse.accepted = false
                        onReleased: mouse.accepted = false
                        onClicked: if (msgBubbleRect.batchLink) bridge.showCwOutlineBatch(msgBubbleRect.msgNums)
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
                    iconName: "up"
                    text: ""
                    kind: "secondary"
                    height: 24
                    onClicked: { cwDock.follow = false; msgList.positionViewAtBeginning() }
                    ToolTip.visible: hovered
                    ToolTip.text: "回到顶部"
                }
                AppButton {
                    iconName: "down"
                    text: ""
                    kind: "secondary"
                    height: 24
                    onClicked: { cwDock.follow = true; cwDock.goToEnd() }
                    ToolTip.visible: hovered
                    ToolTip.text: "跳到底部（并跟随新消息）"
                }
            }
            Connections {
                target: bridge
                // AI 开始输出：仅当用户处于跟随态才回底（#6）
                function onCwBusyChanged() {
                    if (cwDock.busy && cwDock.follow)
                        Qt.callLater(cwDock.goToEnd)
                }
                // 流式增量：跟随态才钉底；用户上翻后不再被拽回
                function onCwStreamingChanged() {
                    if (cwDock.busy && cwDock.follow)
                        Qt.callLater(cwDock.goToEnd)
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
            // 回应模式开关（方案 A）：讨论=确认收敛短回复；撰写=输入即产出草案。
            // 默认讨论——「发两三个字收七百字」从交互层面根治。
            Row {
                spacing: 2
                Layout.alignment: Qt.AlignBottom
                Rectangle {
                    width: 46; height: 30
                    radius: Theme.rBtn
                    color: !cwDock.composeMode ? Theme.bgActive : Theme.bgHover
                    border.width: 1
                    border.color: !cwDock.composeMode ? Theme.accent : Theme.border
                    Text { anchors.centerIn: parent; text: "讨论"; color: !cwDock.composeMode ? Theme.accent : Theme.textTertiary
                           font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: cwDock.composeMode = false }
                }
                Rectangle {
                    width: 46; height: 30
                    radius: Theme.rBtn
                    color: cwDock.composeMode ? Theme.bgActive : Theme.bgHover
                    border.width: 1
                    border.color: cwDock.composeMode ? Theme.accent : Theme.border
                    Text { anchors.centerIn: parent; text: "撰写"; color: cwDock.composeMode ? Theme.accent : Theme.textTertiary
                           font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: cwDock.composeMode = true }
                }
            }
            // 输入区：随内容增高（旧 TextField 不折行且 height 写死 30，
            // 第二行起根本看不见），超过上限后内部滚动
            ScrollView {
                id: cwInputScroll
                objectName: "cwInputScroll"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(Math.max(32, cwInput.contentHeight + 14), 140)
                clip: true
                TextArea {
                    id: cwInput
                    objectName: "cwInput"
                    wrapMode: TextArea.Wrap
                    placeholderText: cwDock.composeMode
                        ? "描述要写什么，直接产出草案…（撰写模式）"
                        : "和 " + bridge.cwAgent + " 讨论，或直接下指令：「回退到去味之前」「重写第2章，铺垫足一点」「现在进度怎么样」…（回车发送）"
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
                    function handleReturn(ev) {
                        ev.accepted = true
                        if (ev.modifiers & Qt.ControlModifier)
                            insert(cursorPosition, "\n")
                        else
                            cwDock.send()
                    }
                    Keys.onReturnPressed: handleReturn(event)
                    Keys.onEnterPressed: handleReturn(event)
                }
            }
            Column {
                spacing: 4
                Layout.alignment: Qt.AlignBottom
                AppButton {
                    objectName: "cwSendButton"
                    text: "发送"
                    kind: "primary"
                    height: 30
                    enabled: cwInput.enabled && cwInput.text.trim() !== ""
                    onClicked: cwDock.send()
                }
                AppButton {
                    text: "生成草案"
                    kind: "secondary"
                    height: 30
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey !== "cw_project"
                    enabled: !cwDock.busy
                    onClicked: bridge.generateCwDraft()
                    ToolTip.visible: hovered
                    ToolTip.text: "跳过讨论，直接按本阶段产物结构产出草案（结果进对话区，标「草案」）"
                }
                AppButton {
                    text: "提取正文到编辑器"
                    kind: "secondary"
                    height: 30
                    visible: cwDock.viewIsCurrent && bridge.cwStageKey === "cw_prose"
                    enabled: !cwDock.busy
                    onClicked: bridge.proseToEditor()
                    ToolTip.visible: hovered
                    ToolTip.text: "从最近一条正文草案中剥出正文本身（去掉开场白/元话语），写进当前打开的章——再点「确定」走锁定"
                }
            }
        }
    }

    // ---- CW-G7：打回确认卡（级联会删下游产物，且已锁定章/追踪不回滚）----
    property var rbDetail: ({})
    Connections {
        target: bridge
        function onRollbackConfirm(stage, detail) {
            cwDock.rbDetail = detail || {}
            rbConfirmDialog.open()
        }
    }
    Dialog {
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
        }
        id: rbConfirmDialog
        objectName: "cwRollbackConfirmDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: "打回到「" + (cwDock.rbDetail.label || "") + "」？将删除 "
                  + (cwDock.rbDetail.count || 0) + " 个下游产物"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
            padding: 16
        }
        contentItem: Column {
            spacing: 8
            width: parent.width
            Text {
                width: parent.width
                text: "级联失效并归档：" + ((cwDock.rbDetail.files || []).length)
                      + " 个产物（细纲/世界书/单元总纲等，可回看归档不丢失）"
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                visible: (cwDock.rbDetail.locked || []).length > 0
                text: "已锁定第 " + (cwDock.rbDetail.locked || []).join("、")
                      + " 章与追踪/伏笔表不会回滚——终稿原样保留"
                color: Theme.danger
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                visible: (cwDock.rbDetail.locked || []).length === 0
                text: "追踪/伏笔表不会回滚"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
            }
            Text {
                width: parent.width
                text: "被删细纲对应章的「已比对/自动改写」痕迹会一并清除，重写后需重新比对"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }
        footer: RowLayout {
            width: parent.width
            Item { Layout.fillWidth: true }
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: { bridge.cancelRollbackCw(); rbConfirmDialog.close() }
            }
            AppButton {
                objectName: "cwRollbackConfirmButton"
                text: "仍要打回"
                kind: "danger"
                onClicked: { bridge.confirmRollbackCw(); rbConfirmDialog.close() }
            }
        }
    }
}
