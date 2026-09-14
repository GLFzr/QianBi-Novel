import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 创作驾驶舱（M3）：阶段卡片 + 运行模式 + 主控制 + 质量四格/趋势
// 人定方向：每个阶段可 查看 / 带指导重生成 —— AI 执行前人可介入
// ============================================================
Item {
    id: pipeline

    signal openChapter(int num)
    signal openProjectFile(string rel)

    property var cards: []
    property var trend: []
    property int trendMaxWords: 1
    property string regenKey: ""
    property string regenLabel: ""
    property string blurb: ""          // 发布物料（标签+简介）
    property bool blurbBusy: false     // 后台生成中

    function refresh() {
        cards = bridge.stageCards()
        trend = bridge.qualityTrend()
        var mx = 1
        for (var i = 0; i < trend.length; i++) mx = Math.max(mx, trend[i].words)
        trendMaxWords = mx
        blurb = bridge.blurbText()
    }
    // 阶段卡图标：Python 侧给的是字符（✦❖☰✍），QML 侧映射到统一线性图标
    function cardIcon(key) {
        if (key === "setting") return "spark"
        if (key === "outline") return "doc"
        if (key === "ch_outline") return "chapters"
        return "pen"
    }
    Component.onCompleted: refresh()
    Connections {
        target: bridge
        function onStageKeyChanged() { pipeline.refresh() }
        function onLastRecordChanged() { pipeline.refresh() }
        function onRunningChanged() { pipeline.refresh() }
        function onProjectOpened() { pipeline.refresh(); modeChip.syncFromBridge() }
        function onCwModeChanged() { modeChip.syncFromBridge() }
        function onRunModeChanged() { modeChip.syncFromBridge() }
        function onGatePresetChanged() {
            gateBlock.preset = bridge.gatePreset()
            // P1-1（评估修复）：checked 绑定无 NOTIFY 依赖，强制重建清单以刷新勾选显示
            gateListRepeater.model = 0
            gateListRepeater.model = bridge.gateMetaList()
        }
        function onBlurbGenerated(ok, text) {
            pipeline.blurbBusy = false
            if (ok) pipeline.blurb = text
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // 头部（统一面板头：56px · fsTitle 粗标题 + 弱化元信息 · 动作右侧）
        Rectangle {
            Layout.fillWidth: true
            height: 56
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 8
                Column {
                    spacing: 1
                    Layout.fillWidth: true
                    Text {
                        text: bridge.bookTitle === "" ? "流水线" : bridge.bookTitle
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        width: parent.width
                    }
                    Text {
                        visible: bridge.bookMeta !== ""
                        text: bridge.bookMeta
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                        elide: Text.ElideRight
                        width: parent.width
                    }
                }
                // 运行模式切换（v1.2 两档制：全自动 / 共写）——两段互斥，点哪进哪
                Rectangle {
                    id: modeChip
                    objectName: "modeChip"
                    function syncFromBridge() {
                        var m = bridge.runMode()
                        segAuto.active = (m === "auto")
                        segCw.active = (m === "cw")
                    }
                    visible: bridge.hasProject
                    width: 148; height: 26; radius: 13
                    color: Theme.bgHover
                    border.width: 1
                    border.color: Theme.border
                    Component.onCompleted: syncFromBridge()
                    Row {
                        anchors.fill: parent
                        spacing: 0
                        Rectangle {
                            id: segAuto
                            property bool active: true
                            width: parent.width / 2; height: parent.height
                            radius: 13
                            color: active ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.centerIn: parent
                                text: "全自动"
                                color: segAuto.active ? Theme.accent : Theme.textTertiary
                                font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: bridge.setRunMode("auto")
                            }
                        }
                        Rectangle {
                            id: segCw
                            property bool active: false
                            width: parent.width / 2; height: parent.height
                            radius: 13
                            color: active ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.centerIn: parent
                                text: "共写"
                                color: segCw.active ? Theme.accent : Theme.textTertiary
                                font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: bridge.setRunMode("cw")
                            }
                        }
                    }
                    ToolTip.visible: modeMa.containsMouse
                    ToolTip.text: "全自动=按下方决策门设置自动/停靠跑完整本书 · 共写=六阶段人机共写（对话讨论+确定定稿）"
                    MouseArea { id: modeMa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth

            ColumnLayout {
                x: 12
                y: 12
                width: parent.width - 24
                spacing: 10

                // ---- 阶段卡片（创作驾驶舱：设定→大纲→细纲→正文）----
                Text {
                    text: "创作阶段 · 每阶段可介入"
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 6
                    rowSpacing: 6

                    Repeater {
                        model: pipeline.cards
                        delegate: Rectangle {
                            id: stageCard
                            required property var modelData
                            objectName: "stageCard_" + modelData.key
                            Layout.fillWidth: true
                            height: 92
                            radius: Theme.rCard
                            color: Theme.bgCard
                            border.width: 1
                            border.color: modelData.status === "active" ? Theme.accentSoft
                                     : modelData.status === "done" ? Theme.border : Theme.border
                            Rectangle {
                                anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                                height: 2; radius: 1
                                color: modelData.status === "active" ? Theme.accent
                                     : modelData.status === "done" ? Theme.success : "transparent"
                            }
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 4
                                RowLayout {
                                    spacing: 6
                                    AppIcon {
                                        name: pipeline.cardIcon(modelData.key)
                                        size: 14
                                        color: modelData.status === "active" ? Theme.accent
                                             : modelData.status === "done" ? Theme.success : Theme.muted
                                    }
                                    Text {
                                        text: modelData.label
                                        color: Theme.textPrimary
                                        font.family: Theme.uiFont
                                        font.pixelSize: Theme.fsSmall
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    AppBadge {
                                        visible: modelData.status !== "active"
                                        text: modelData.status === "done" ? "完成" : "待开始"
                                        tint: modelData.status === "done" ? Theme.success : Theme.muted
                                    }
                                    // 待机圈：该阶段已进入但未完成——旋转圆点绕暗环（全自动档/演示档通用）
                                    Row {
                                        visible: modelData.status === "active"
                                        spacing: 5
                                        Item {
                                            width: 13; height: 13
                                            anchors.verticalCenter: parent.verticalCenter
                                            Rectangle {
                                                anchors.fill: parent; radius: Theme.rMd /*8→8*/; color: "transparent"
                                                border.width: 2
                                                border.color: Theme.accentSoft
                                            }
                                            Item {
                                                id: stageOrbit
                                                anchors.fill: parent
                                                Rectangle {
                                                    width: 5; height: 5; radius: 2.5
                                                    color: Theme.accent
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    anchors.top: parent.top; anchors.topMargin: -1
                                                }
                                                RotationAnimation on rotation {
                                                    from: 0; to: 360; duration: Theme.durLoop / 2; loops: Animation.Infinite
                                                    // P2-1：motionOK 与运行态同闸（原 running 唯一化，消重复赋值）
                                                    running: modelData.status === "active" && Theme.motionOK
                                                }
                                            }
                                        }
                                        Text {
                                            text: "进行中"
                                            color: Theme.accent
                                            font.family: Theme.uiFont
                                            font.pixelSize: Theme.fsMicro
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                }
                                Text {
                                    text: modelData.detail
                                    color: Theme.textTertiary
                                    font.family: Theme.monoFont
                                    font.pixelSize: Theme.fsMicro
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                                Row {
                                    spacing: 4
                                    Layout.alignment: Qt.AlignRight
                                    AppButton {
                                        text: "查看"
                                        height: 24
                                        visible: modelData.file !== ""
                                        onClicked: pipeline.openProjectFile(modelData.file)
                                    }
                                    AppButton {
                                        text: "重生成"
                                        height: 24
                                        visible: modelData.key !== "prose"
                                        enabled: !bridge.isRunning
                                        onClicked: {
                                            pipeline.regenKey = modelData.key
                                            pipeline.regenLabel = modelData.label
                                            regenDialog.open()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                StageStepper {
                    Layout.fillWidth: true
                    stageKey: bridge.stageKey
                    proseProgress: bridge.progressText
                }

                // 进度条
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "全书进度"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: bridge.progressPercentText
                        color: Theme.accent
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.monoFont
                    }
                }
                ThinProgress { Layout.fillWidth: true; value: bridge.progressValue; indeterminate: bridge.isRunning }

                // 连写模式（F3）：开启后所有决策门自动放行，批量跑批不等人
                AppCheck {
                    id: autoGateCheck
                    Layout.fillWidth: true
                    text: "连写模式：决策门（大纲/细纲/审校/定稿）自动放行，跑批不等人"
                    checked: bridge.autoGate
                    font.pixelSize: Theme.fsTiny
                    onToggled: bridge.setAutoGate(checked)
                }

                // 离峰挂机（v4 分时价）：peak 时段自动挂起等待，off-peak 自动续跑
                AppCheck {
                    id: offpeakCheck
                    Layout.fillWidth: true
                    text: "离峰挂机：DeepSeek 高价时段（北京时间工作日上午/午后）自动等待，半价时段自动续跑"
                    checked: bridge.offpeakRun
                    font.pixelSize: Theme.fsTiny
                    onToggled: bridge.setOffpeakRun(checked)
                }

                // 主控制
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppButton {
                        objectName: "startButton"
                        visible: !bridge.isRunning
                        text: "开始"
                        kind: "primary"
                        Layout.fillWidth: true
                        onClicked: bridge.startPipeline()
                    }
                    AppButton {
                        visible: bridge.isRunning && !bridge.isPaused && !bridge.isStopping
                        text: "暂停"
                        Layout.fillWidth: true
                        onClicked: bridge.pausePipeline()
                    }
                    AppButton {
                        visible: bridge.isRunning && bridge.isPaused && !bridge.isStopping
                        text: "继续"
                        kind: "primary"
                        Layout.fillWidth: true
                        onClicked: bridge.resumePipeline()
                    }
                    AppButton {
                        visible: bridge.isRunning
                        text: bridge.isStopping ? "正在停止…" : "停止"
                        kind: "danger"
                        enabled: !bridge.isStopping
                        Layout.fillWidth: true
                        onClicked: bridge.stopPipeline()
                    }
                }

                // 决策门（v1.2 用户裁决）：仅流水线档显示；「逐步确认」「边界确认」两按钮
                // 互斥——可同关（=全自动放行）、不可同开；边界确认开启时下方拉出勾选清单
                ColumnLayout {
                    id: gateBlock
                    objectName: "gateBlock"
                    property string preset: bridge.gatePreset()
                    readonly property bool cwOn: bridge.cwMode === "cw"
                    visible: bridge.hasProject && !cwOn
                    Layout.fillWidth: true
                    spacing: 6
                    Text {
                        Layout.fillWidth: true
                        visible: bridge.autoGate
                        text: "连写模式开启中：所有决策门自动放行（下方开关暂不生效）"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsMicro
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text {
                            text: "决策门"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                        }
                        Rectangle {
                            id: stepBtn
                            property bool on: gateBlock.preset === "step"
                            width: 92; height: 26; radius: 13
                            color: on ? Theme.accentSoft : Theme.bgHover
                            border.width: 1
                            border.color: on ? Theme.accent : Theme.border
                            Row {
                                anchors.centerIn: parent
                                spacing: 5
                                Rectangle {
                                    width: 7; height: 7; radius: 3.5
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: stepBtn.on ? Theme.accent : Theme.muted
                                }
                                Text {
                                    text: "逐步确认"
                                    color: stepBtn.on ? Theme.accent : Theme.textSecondary
                                    font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: bridge.setGatePreset(stepBtn.on ? "off" : "step")
                            }
                            ToolTip.visible: stepMa.containsMouse
                            ToolTip.text: "开=每个决策门都停靠等你确认（原逐步确认档）"
                            MouseArea { id: stepMa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                        Rectangle {
                            id: borderBtn
                            property bool on: gateBlock.preset === "border"
                            width: 92; height: 26; radius: 13
                            color: on ? Theme.accentSoft : Theme.bgHover
                            border.width: 1
                            border.color: on ? Theme.accent : Theme.border
                            Row {
                                anchors.centerIn: parent
                                spacing: 5
                                Rectangle {
                                    width: 7; height: 7; radius: 3.5
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: borderBtn.on ? Theme.accent : Theme.muted
                                }
                                Text {
                                    text: "边界确认"
                                    color: borderBtn.on ? Theme.accent : Theme.textSecondary
                                    font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: bridge.setGatePreset(borderBtn.on ? "off" : "border")
                            }
                            ToolTip.visible: borderMa.containsMouse
                            ToolTip.text: "开=只在你勾选的步骤停靠（下方清单可勾选）"
                            MouseArea { id: borderMa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                        Text {
                            Layout.fillWidth: true
                            // 怪值落入 off 分支（gate_enabled 对未知值返回 False，语义一致）
                            text: gateBlock.preset === "step" ? "每个决策门都停靠"
                                 : gateBlock.preset === "border" ? "只停勾选的步骤"
                                 : "两个都关：全部自动放行"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont; font.pixelSize: Theme.fsMicro
                            elide: Text.ElideRight
                        }
                    }
                    // 边界确认清单：开「边界确认」后在下方拉出，逐门勾选即时生效
                    GridLayout {
                        visible: gateBlock.preset === "border"
                        Layout.fillWidth: true
                        columns: 3
                        columnSpacing: 10
                        rowSpacing: 4
                        Repeater {
                            id: gateListRepeater
                            model: bridge.gateMetaList()
                            delegate: AppCheck {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.label
                                checked: bridge.gateEnabled(modelData.key)
                                font.pixelSize: Theme.fsMicro
                                onToggled: bridge.setGateEnabled(modelData.key, checked)
                                ToolTip.visible: hovered
                                ToolTip.text: modelData.desc
                            }
                        }
                    }
                }

                StepPills {
                    objectName: "stepPills"
                    currentStep: bridge.currentStepKey
                    running: bridge.isRunning && !bridge.isPaused
                }

                // 质量四格（AppStatTile：数字为主，语义色只落在数值上）
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 6
                    rowSpacing: 6
                    Repeater {
                        model: [
                            { "label": "AI味阻断", "key": "deslop_blocking", "bad": true },
                            { "label": "审校阻塞", "key": "review_blocking", "bad": true },
                            { "label": "AI味建议", "key": "deslop_advisory", "bad": false },
                            { "label": "本章字数", "key": "words", "bad": false }
                        ]
                        delegate: AppStatTile {
                            required property var modelData
                            Layout.fillWidth: true
                            label: modelData.label
                            value: bridge.lastRecord[modelData.key] !== undefined ? String(bridge.lastRecord[modelData.key]) : "—"
                            valueColor: modelData.bad && bridge.lastRecord[modelData.key] > 0 ? Theme.danger
                                        : Theme.textPrimary
                        }
                    }
                }

                // 质量历史趋势（近 20 章：中性柱=字数 · 红点=有阻断）
                Rectangle {
                    Layout.fillWidth: true
                    visible: pipeline.trend.length >= 2
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border
                    height: 86
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4
                        Text {
                            text: "质量趋势 · 近 " + pipeline.trend.length + " 章（柱=字数 · 红点=有阻断）"
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                        }
                        Row {
                            spacing: 3
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Repeater {
                                model: pipeline.trend
                                delegate: Item {
                                    required property var modelData
                                    width: parent.width / pipeline.trend.length - 3
                                    height: parent.height
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        anchors.bottom: parent.bottom
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: Math.max(4, parent.width - 2)
                                        height: Math.max(3, parent.height * modelData.words / pipeline.trendMaxWords)
                                        radius: 2
                                        color: modelData.blocking > 0 ? Theme.dangerSoft
                                             : Theme.bgActive
                                    }
                                    // 阻断标记：柱顶小红点（语义色只占小面积）
                                    Rectangle {
                                        visible: modelData.blocking > 0
                                        anchors.bottom: parent.bottom
                                        anchors.bottomMargin: Math.max(3, parent.height * modelData.words / pipeline.trendMaxWords) + 3
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 5; height: 5; radius: 2.5
                                        color: Theme.danger
                                    }
                                    ToolTip.visible: barHot.containsMouse
                                    ToolTip.text: "第" + modelData.num + "章 · " + modelData.words + "字 · 阻断" + modelData.blocking + " 建议" + modelData.advisory
                                    MouseArea { id: barHot; anchors.fill: parent; hoverEnabled: true }
                                }
                            }
                        }
                    }
                }

                // ---- 发布物料：标签 + 简介（据全书大纲/核心设定生成）----
                Rectangle {
                    Layout.fillWidth: true
                    visible: bridge.hasProject
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border
                    height: blurbCol.implicitHeight + 20
                    ColumnLayout {
                        id: blurbCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text {
                                text: "发布物料 · 标签与简介"
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsSmall
                                font.bold: true
                            }
                            AppBadge {
                                visible: pipeline.blurb !== ""
                                text: "已保存"
                                tint: Theme.success
                            }
                            Item { Layout.fillWidth: true }
                            AppButton {
                                text: pipeline.blurb === "" ? "生成" : "重新生成"
                                height: 24
                                enabled: !bridge.isRunning && !pipeline.blurbBusy
                                onClicked: {
                                    pipeline.blurbBusy = true
                                    bridge.generateBlurb()
                                }
                            }
                            AppButton {
                                text: "打开文件"
                                height: 24
                                kind: "ghost"
                                visible: pipeline.blurb !== ""
                                onClicked: pipeline.openProjectFile("设定/简介与标签.md")
                            }
                        }
                        Text {
                            visible: pipeline.blurbBusy
                            text: "生成中…（辅助槽，约 30-60 秒）"
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                        }
                        Rectangle {
                            visible: pipeline.blurb !== "" && !pipeline.blurbBusy
                            Layout.fillWidth: true
                            height: 150
                            radius: Theme.rBtn
                            color: Theme.bgLog
                            border.width: 1
                            border.color: Theme.border
                            clip: true
                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 2
                                TextArea {
                                    readOnly: true
                                    text: pipeline.blurb
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

                // 快捷操作
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    AppButton {
                        text: "重写本章"
                        enabled: !bridge.isRunning && bridge.lastRecord.num !== undefined
                        Layout.fillWidth: true
                        onClicked: {
                            pipeline.regenKey = "chapter:" + bridge.lastRecord.num
                            pipeline.regenLabel = "第 " + bridge.lastRecord.num + " 章"
                            regenDialog.open()
                        }
                    }
                    AppButton {
                        text: "打开最新"
                        enabled: bridge.lastRecord.num !== undefined
                        Layout.fillWidth: true
                        onClicked: pipeline.openChapter(bridge.lastRecord.num)
                    }
                }

                Item { height: 8 }
            }
        }
    }

    // ---- 阶段重生成对话框（查看产物 / 带指导重生成）----
    Dialog {
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
        }
        id: regenDialog
        objectName: "regenDialog"
        parent: Overlay.overlay
        modal: true
        width: 480
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
        padding: 18
        background: DialogBg {}
        header: Text {
            text: pipeline.regenKey.indexOf("chapter:") === 0
                  ? "重写 " + (pipeline.regenLabel || "本章") + "？"
                  : "重生成「" + (pipeline.regenLabel || "该阶段") + "」？"
            color: Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTitle
            font.weight: Font.DemiBold
            padding: 16
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                visible: pipeline.regenKey.indexOf("chapter:") !== 0
                width: parent.width
                text: "将删除该阶段产物，点「开始」后从该阶段重新生成。" + (pipeline.regenKey === "outline" ? "\n注意：大纲重生成会连带清除全部细纲。" : "")
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                visible: pipeline.regenKey.indexOf("chapter:") === 0
                width: parent.width
                text: "当前正文将被移除并重新生成。旧内容会先归档为「重写前备份」版本——不满意可在版本历史回退。"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                text: "重生成指导（可选，注入生成 prompt）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            TextArea {
                id: regenGuidance
                width: parent.width
                height: 68
                placeholderText: "如：设定里把世界观改得更黑暗；大纲按三幕式重排；本章打脸再狠一点…"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
                background: Rectangle {
                    radius: Theme.rBtn
                    color: Theme.bgHover
                    border.width: 1
                    border.color: Theme.border
                }
            }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: regenDialog.close()
            }
            AppButton {
                text: "确认重生成"
                kind: "primary"
                onClicked: {
                    if (pipeline.regenKey.indexOf("chapter:") === 0)
                        bridge.rewriteChapterWithGuidance(parseInt(pipeline.regenKey.substring(8)), regenGuidance.text)
                    else
                        bridge.regenerateStage(pipeline.regenKey, regenGuidance.text)
                    pipeline.refresh()
                    regenGuidance.text = ""
                    regenDialog.close()
                }
            }
        }
    }
}
