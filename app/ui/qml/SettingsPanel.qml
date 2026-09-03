import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// 设置面板：连接与模型 · 写作偏好 · 外观（编辑器/阅读） · 备份与快捷键
Item {
    id: settings
    objectName: "settingsPanel"

    property string editingId: ""
    property bool isNew: false
    property int settingsTab: 0
    property var wp: ({})
    property var ep: ({ fontScale: 1.0, narrow: true })
    property string regexSem: "logic"

    ListModel { id: modelList }

    function refreshPrefs() {
        wp = bridge.writingPrefs()
        ep = bridge.editorPrefs()
        wordTargetSpin.value = bridge.chapterWordTarget()
        reviewSwitch.checked = bridge.reviewEnabled()
        autoBackupSwitch.checked = bridge.autoBackupEnabled()
        regexSem = bridge.regexSemantics()
    }
    Component.onCompleted: {
        refreshPrefs()
        var opts = bridge.connectionOptions()
        if (opts.length > 0) startEdit(opts[0].id)
        else startNew()
    }
    Connections {
        target: bridge
        function onModelsFetched(cid, models) {
            if (models.length > 0) {
                modelList.clear()
                for (var i = 0; i < models.length; i++) modelList.append({ "m": models[i] })
                modelField.currentIndex = 0
                bridge.showToast("ok", "拉取到 " + models.length + " 个模型，可从下拉选择")
            } else {
                bridge.showToast("warn", "未拉取到模型（接口不支持 /models 或连接失败）")
            }
        }
        function onConnTestResult(cid, ok, msg) {
            bridge.showToast(ok ? "ok" : "error", msg)
        }
    }

    function currentModelName() {
        if (modelField.editable && modelField.editText !== "")
            return modelField.editText
        return modelField.currentText
    }

    function currentThinking() {
        switch (thinkingModeCombo.currentIndex) {
        case 1: return "disabled"
        case 2: return "enabled"
        default: return ""
        }
    }

    function currentEffort() {
        var v = effortCombo.currentText
        return (v === "默认" || v === "") ? "" : v
    }

    function startNew() {
        editingId = ""
        isNew = true
        nameField.text = ""
        providerCombo.currentIndex = 0
        urlField.text = bridge.providerOptions[0].baseUrl
        keyField.text = ""
        modelField.currentIndex = -1
        modelField.editText = ""
        tempSpin.value = 7
        maxTokensSpin.value = 8192
        timeoutSpin.value = 300
        thinkingModeCombo.currentIndex = 0
        effortCombo.currentIndex = 0
    }

    function startEdit(cid) {
        editingId = cid
        isNew = false
        var c = bridge.getConnection(cid)
        nameField.text = c.name || ""
        var prov = c.provider || "custom"
        for (var p = 0; p < bridge.providerOptions.length; p++)
            if (bridge.providerOptions[p].key === prov) providerCombo.currentIndex = p
        urlField.text = c.base_url || ""
        keyField.text = c.api_key || ""
        modelField.currentIndex = -1
        modelField.editText = c.model || ""
        tempSpin.value = Math.round((c.temperature !== undefined ? c.temperature : 0.7) * 10)
        maxTokensSpin.value = c.max_tokens || 8192
        timeoutSpin.value = c.timeout || 300
        var th = c.thinking || ""
        thinkingModeCombo.currentIndex = th === "disabled" ? 1 : (th === "enabled" ? 2 : 0)
        var ef = c.reasoning_effort || ""
        effortCombo.currentIndex = ef === "low" ? 1 : (ef === "high" ? 2 : (ef === "max" ? 3 : 0))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            height: 66
            color: Theme.bgPanel
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                Row {
                    spacing: 8
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    Text {
                        text: "设置"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }
                    Text {
                        text: ["连接与模型 · 任务槽位", "写作偏好 · 闸门", "编辑器 · 阅读", "备份 · 快捷键"][settings.settingsTab]
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                }
                AppButton {
                    visible: settings.settingsTab === 0
                    text: "＋"
                    height: 28
                    onClicked: settings.startNew()
                }
            }

            // 标签栏（下划线式 · 现代 tab）
            Row {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 0
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 2
                Repeater {
                    model: ["连接与模型", "写作偏好", "外观", "系统"]
                    delegate: Item {
                        required property string modelData
                        required property int index
                        height: 30
                        width: tabLabel.implicitWidth + 16
                        Text {
                            id: tabLabel
                            anchors.centerIn: parent
                            text: parent.modelData
                            color: settings.settingsTab === index ? Theme.textPrimary : Theme.textTertiary
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.uiFont
                            font.bold: settings.settingsTab === index
                        }
                        Rectangle {
                            visible: settings.settingsTab === index
                            anchors.bottom: parent.bottom
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width - 8
                            height: 2
                            radius: 1
                            color: Theme.accent
                        }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: settings.settingsTab = index }
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: settings.settingsTab

            // ============ 页0：连接与模型 ============
            ColumnLayout {
                spacing: 0

        // ---- 连接与模型适配说明 ----
        Rectangle {
            Layout.fillWidth: true
            Layout.margins: 10
            radius: Theme.rCard
            color: Qt.rgba(Theme.info.r, Theme.info.g, Theme.info.b, 0.07)
            border.width: 1
            border.color: Qt.rgba(Theme.info.r, Theme.info.g, Theme.info.b, 0.3)
            implicitHeight: apiNoteCol.implicitHeight + 20
            ColumnLayout {
                id: apiNoteCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 3
                Text {
                    text: "ℹ 关于连接与提示词适配"
                    color: Theme.info
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    text: "内置提示词（正文写作 / 去味 / 审校等全部 prompt 工程）只适配各家平台的 DeepSeek API（V4 系 thinking / reasoning_effort / 参数习惯）。\n内置官方预设仅两家：DeepSeek 官方、OpenCode Go 官方；其余第三方（中转 / 本地 Ollama / LM Studio 等）请用「自定义」自行接入，非 DeepSeek 模型写作质量与闸门稳定性可能打折。"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                    wrapMode: Text.Wrap
                    lineHeight: 1.5
                }
            }
        }

        // ---- 连接列表（横向滚动条）----
        ListView {
            Layout.fillWidth: true
            height: 54
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            anchors.margins: 10
            model: bridge.connectionModelProp
            delegate: Rectangle {
                required property string cid
                required property string name
                required property string model
                required property int index
                width: 172
                height: 52
                radius: 9
                color: settings.editingId === cid && !settings.isNew ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                     : hover.containsMouse ? Theme.bgHover : Theme.bgCard
                border.width: 1
                border.color: settings.editingId === cid && !settings.isNew ? Theme.accent : Theme.border
                Rectangle { anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; height: 1
                           color: Theme.cardHighlight }
                Column {
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 3
                    Text {
                        width: parent.width
                        text: name
                        color: Theme.textPrimary
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.uiFont
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: model
                        color: settings.editingId === cid && !settings.isNew ? Theme.accent : Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.monoFont
                        elide: Text.ElideRight
                    }
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: settings.startEdit(cid)
                }
            }
        }

        // ---- 编辑表单 ----
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                Layout.margins: 12
                spacing: 10

                AppField { id: nameField; Layout.fillWidth: true; label: "名称"; placeholder: "连接名称" }

                Column {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "服务商"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                    ComboBox {
                        id: providerCombo
                        width: parent.width
                        model: bridge.providerOptions.map(function (p) { return p.label })
                        palette.window: Theme.bgCard
                        palette.text: Theme.textPrimary
                        palette.buttonText: Theme.textPrimary
                        background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        onActivated: urlField.text = bridge.providerOptions[currentIndex].baseUrl
                    }
                }

                AppField { id: urlField; Layout.fillWidth: true; label: "Base URL" }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppField {
                        id: keyField
                        Layout.fillWidth: true
                        label: "API Key"
                        echoMode: showKey.checked ? TextInput.Normal : TextInput.Password
                        placeholder: "sk-…"
                    }
                    AppButton {
                        id: showKey
                        text: showKey.checked ? "隐藏" : "显示"
                        Layout.alignment: Qt.AlignBottom
                        checkable: true
                    }
                }

                Column {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "模型名（可下拉选择或手动输入）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                    RowLayout {
                        width: parent.width
                        spacing: 6
                        ComboBox {
                            id: modelField
                            Layout.fillWidth: true
                            editable: true
                            model: modelList
                            textRole: "m"
                            palette.window: Theme.bgCard
                            palette.base: Theme.bgCard
                            palette.text: Theme.textPrimary
                            palette.buttonText: Theme.textPrimary
                            background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        }
                        AppButton {
                            text: "拉取"
                            Layout.alignment: Qt.AlignVCenter
                            onClicked: {
                                if (settings.editingId && !settings.isNew) bridge.fetchModels(settings.editingId)
                                else bridge.showToast("warn", "请先保存连接再拉取模型列表")
                            }
                        }
                    }
                }

                Row {
                    Layout.fillWidth: true
                    spacing: 8
                    Column {
                        spacing: 6
                        width: (parent.width - 16) * 0.26
                        Text { text: "温度"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        AppSpinBox { id: tempSpin; width: parent.width; from: 0; to: 20; value: 7; overrideText: (tempSpin.value / 10).toFixed(1) }
                    }
                    Column {
                        spacing: 6
                        width: (parent.width - 16) * 0.48
                        Text { text: "max_tokens"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        AppSpinBox { id: maxTokensSpin; width: parent.width; from: 512; to: 131072; stepSize: 1024; value: 8192 }
                    }
                    Column {
                        spacing: 6
                        width: (parent.width - 16) * 0.26
                        Text { text: "超时(秒)"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        AppSpinBox { id: timeoutSpin; width: parent.width; from: 30; to: 3600; stepSize: 30; value: 300 }
                    }
                }

                Row {
                    Layout.fillWidth: true
                    spacing: 8
                    Column {
                        spacing: 6
                        width: (parent.width - 8) / 2
                        Text { text: "思考模式"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        ComboBox {
                            id: thinkingModeCombo
                            width: parent.width
                            model: ["默认", "禁用", "启用"]
                            palette.window: Theme.bgCard
                            palette.text: Theme.textPrimary
                            palette.buttonText: Theme.textPrimary
                            background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        }
                    }
                    Column {
                        spacing: 6
                        width: (parent.width - 8) / 2
                        Text { text: "思考强度"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        ComboBox {
                            id: effortCombo
                            width: parent.width
                            model: ["默认", "low", "high", "max"]
                            enabled: thinkingModeCombo.currentIndex === 2
                            opacity: enabled ? 1.0 : 0.45
                            palette.window: Theme.bgCard
                            palette.text: Theme.textPrimary
                            palette.buttonText: Theme.textPrimary
                            background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    AppButton {
                        text: "测试连接"
                        onClicked: bridge.testConnectionDraft({
                            "id": settings.editingId || "__draft__",
                            "name": nameField.text,
                            "provider": bridge.providerOptions[providerCombo.currentIndex].key,
                            "base_url": urlField.text,
                            "api_key": keyField.text,
                            "model": settings.currentModelName(),
                            "temperature": tempSpin.value / 10,
                            "max_tokens": maxTokensSpin.value,
                            "timeout": timeoutSpin.value,
                            "thinking": settings.currentThinking(),
                            "reasoning_effort": settings.currentEffort()
                        })
                    }
                    AppButton {
                        text: settings.isNew ? "创建" : "保存"
                        kind: "primary"
                        onClicked: {
                            bridge.saveConnection({
                                "id": settings.editingId,
                                "name": nameField.text || "未命名连接",
                                "provider": bridge.providerOptions[providerCombo.currentIndex].key,
                                "base_url": urlField.text,
                                "api_key": keyField.text,
                                "model": settings.currentModelName(),
                                "temperature": tempSpin.value / 10,
                                "max_tokens": maxTokensSpin.value,
                                "timeout": timeoutSpin.value,
                                "thinking": settings.currentThinking(),
                                "reasoning_effort": settings.currentEffort()
                            })
                            settings.isNew = false
                        }
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: "删除"
                        kind: "danger"
                        enabled: !settings.isNew && settings.editingId !== ""
                        onClicked: { bridge.deleteConnection(settings.editingId); settings.startNew() }
                    }
                }

                // ---- 槽位绑定 ----
                Rectangle {
                    Layout.fillWidth: true
                    radius: Theme.rCard
                    color: Theme.bgCard
                    implicitHeight: slotCol.implicitHeight + 24
                    Column {
                        id: slotCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: 8
                        Text {
                            text: "任务槽位绑定"
                            color: Theme.textPrimary
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.uiFont
                            font.bold: true
                        }
                        Repeater {
                            model: [
                                { "slot": "writing", "label": "写作槽" },
                                { "slot": "helper", "label": "辅助槽" },
                                { "slot": "review", "label": "审校槽" }
                            ]
                            delegate: Row {
                                width: parent.width
                                spacing: 10
                                Text {
                                    width: 52
                                    text: modelData.label
                                    color: Theme.textSecondary
                                    font.pixelSize: Theme.fsSmall
                                    font.family: Theme.uiFont
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                ComboBox {
                                    id: slotCombo
                                    width: parent.width - 66
                                    property string slotKey: modelData.slot
                                    model: bridge.connectionOptions().map(function (c) { return c.name })
                                    palette.window: Theme.bgCard
                                    palette.text: Theme.textPrimary
                                    palette.buttonText: Theme.textPrimary
                                    background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                                    Component.onCompleted: refreshCurrent()
                                    function refreshCurrent() {
                                        var opts = bridge.connectionOptions()
                                        for (var i = 0; i < opts.length; i++) {
                                            if (opts[i].boundSlots && opts[i].boundSlots.indexOf(slotKey) >= 0) {
                                                currentIndex = i
                                                return
                                            }
                                        }
                                        currentIndex = 0
                                    }
                                    onActivated: {
                                        var opts = bridge.connectionOptions()
                                        if (currentIndex >= 0 && currentIndex < opts.length)
                                            bridge.setSlot(slotKey, opts[currentIndex].id)
                                    }
                                    Connections {
                                        target: bridge
                                        function onSlotsTextChanged() { slotCombo.refreshCurrent() }
                                    }
                                }
                            }
                        }
                        Text {
                            width: parent.width
                            text: "建议：审校槽绑定 pro 档连接（判定更稳，约 2-3 倍 token 成本）；flash 档也能用，但边界判分更容易摇摆。审校判定已统一低温运行，无需改连接档案的温度。"
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                            wrapMode: Text.Wrap
                        }
                    }
                }

                Item { height: 20 }
            }
        }
            }

            // ============ 页1：写作偏好 ============
            ScrollView {
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 12
                    Layout.margins: 12

                    Text {
                        text: "写作偏好"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }

                    // 章节字数目标
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: wtCol.implicitHeight + 24
                        ColumnLayout {
                            id: wtCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 4
                            Text { text: "章节字数目标"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text { text: "草稿低于目标（含容差）会自动扩写一轮"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                spacing: 8
                                Layout.fillWidth: true
                                AppSpinBox { id: wordTargetSpin; from: 500; to: 20000; stepSize: 100; value: 3000 }
                                Text { text: "字 / 章"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny }
                                Item { Layout.fillWidth: true }
                                AppButton { text: "应用"; kind: "primary"; height: 26; onClicked: bridge.setChapterWordTarget(wordTargetSpin.value) }
                            }
                        }
                    }

                    // 审校开关
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: rvCol.implicitHeight + 24
                        ColumnLayout {
                            id: rvCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 4
                            Text { text: "一致性审校"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text { text: "每章定稿前用审校槽做一致性检查，阻塞问题自动修一轮"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true
                                Item { Layout.fillWidth: true }
                                AppCheck {
                                    id: reviewSwitch
                                    text: checked ? "已启用" : "已停用"
                                    font.pixelSize: Theme.fsSmall
                                    palette.text: Theme.textPrimary
                                    onCheckedChanged: if (activeFocus) bridge.setReviewEnabled(checked)
                                }
                            }
                        }
                    }

                    // 逐步确认默认模式
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: modeCol.implicitHeight + 24
                        ColumnLayout {
                            id: modeCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 4
                            Text { text: "默认运行模式"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text { text: "逐步确认：每章定稿后暂停等你确认；自动续写：一口气写到底（运行中也可在驾驶舱切换）"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true
                                Item { Layout.fillWidth: true }
                                AppCheck {
                                    id: stepSwitch
                                    checked: settings.wp.stepConfirm === true
                                    text: checked ? "逐步确认" : "自动续写"
                                    font.pixelSize: Theme.fsSmall
                                    palette.text: Theme.textPrimary
                                    onCheckedChanged: if (activeFocus) bridge.setStepConfirm(checked)
                                }
                            }
                        }
                    }

                    // 「正则」语义（共写档世界书阶段产物；默认逻辑约束规则集）
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: rgCol.implicitHeight + 24
                        ColumnLayout {
                            id: rgCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 4
                            Text { text: "「正则」语义"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text { text: "逻辑约束规则集=必须成立的规则清单（默认，推荐）；字面正则样本=正则表达式样本。只影响解析与写入结构，不阻塞核心路径。"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Row {
                                spacing: 6
                                Layout.fillWidth: true
                                Repeater {
                                    model: [["逻辑约束规则集", "logic"], ["字面正则样本", "regex"]]
                                    delegate: Rectangle {
                                        required property var modelData
                                        height: 26
                                        width: rgText.implicitWidth + 18
                                        radius: 7
                                        color: settings.regexSem === modelData[1] ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                                        border.width: 1
                                        border.color: settings.regexSem === modelData[1] ? Theme.accent : Theme.border
                                        Text {
                                            id: rgText
                                            anchors.centerIn: parent
                                            text: modelData[0]
                                            color: settings.regexSem === modelData[1] ? Theme.accent : Theme.textTertiary
                                            font.pixelSize: Theme.fsTiny
                                            font.family: Theme.uiFont
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: bridge.setRegexSemantics(modelData[1])
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 读改揣摩（M4：共写档保存有变 → review 槽读一遍揣摩意图）
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: rbCol.implicitHeight + 24
                        ColumnLayout {
                            id: rbCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 4
                            Text { text: "读改揣摩（共写档）"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text { text: "保存正文有改动时，Agent 读一遍改动、揣摩你的修改意图（复用审校槽，默认开）。改动量低于阈值不触发；可手动「读一遍」。"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                AppCheck {
                                    id: readbackSwitch
                                    checked: bridge.readbackEnabled
                                    text: checked ? "已开启" : "已关闭"
                                    font.pixelSize: Theme.fsSmall
                                    palette.text: Theme.textPrimary
                                    onCheckedChanged: if (activeFocus) bridge.setReadbackOnSave(checked)
                                }
                                Item { Layout.fillWidth: true }
                                Text { text: "最小改动量"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                                AppSpinBox { id: readbackDiffSpin; from: 0; to: 2000; stepSize: 50; value: bridge.readbackMinDiff }
                                AppButton { text: "应用"; kind: "primary"; height: 26; onClicked: bridge.setReadbackMinDiff(readbackDiffSpin.value) }
                            }
                        }
                    }

                    // 全局写作偏好入口（在创作笔记面板）
                    Text {
                        Layout.fillWidth: true
                        text: "💡 全局写作偏好（文风 / 禁忌 / 节奏，注入所有章节）在左侧「笔记」面板维护。"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                        wrapMode: Text.Wrap
                    }

                    Item { height: 8 }
                }
            }

            // ============ 页2：外观（编辑器 + 阅读） ============
            ScrollView {
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 12
                    Layout.margins: 12

                    // ---- v0.13：主题切换（夜间/羊皮纸/纯白）----
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: themeCol.implicitHeight + 20
                        ColumnLayout {
                            id: themeCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 8
                            Text {
                                text: "界面主题（v0.13 新增 3 主题）"
                                color: Theme.textPrimary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsBody
                                font.bold: true
                            }
                            Text {
                                text: "切换实时生效；快捷键 Ctrl+T 在三主题间循环"
                                color: Theme.textTertiary
                                font.family: Theme.uiFont
                                font.pixelSize: Theme.fsTiny
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Repeater {
                                    model: [
                                        { id: "qianbi_night", label: "夜间", desc: "默认·中性灰" },
                                        { id: "qianbi_parchment", label: "羊皮纸", desc: "亮色·暖黄" },
                                        { id: "qianbi_plain", label: "纯白", desc: "亮色·冷白" }
                                    ]
                                    delegate: AppButton {
                                        required property var modelData
                                        text: modelData.label
                                        kind: bridge.currentTheme() === modelData.id ? "primary" : "default"
                                        Layout.fillWidth: true
                                        height: 32
                                        onClicked: bridge.setTheme(modelData.id)
                                    }
                                }
                            }
                        }
                    }

                    // ---- v0.13：预设库入口快捷跳转 ----
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: libRow.implicitHeight + 20
                        RowLayout {
                            id: libRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    text: "预设库（独立面板）"
                                    color: Theme.textPrimary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsBody
                                    font.bold: true
                                }
                                Text {
                                    text: "浏览 9 套 v2 题材预设 · 6 阶段 hint 预览 · 导入/导出"
                                    color: Theme.textTertiary
                                    font.family: Theme.uiFont
                                    font.pixelSize: Theme.fsTiny
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                            AppButton {
                                text: "打开预设库 →"
                                kind: "primary"
                                height: 32
                                onClicked: mainWindow.activePanel = "library"
                            }
                        }
                    }

                    Text {
                        text: "编辑器外观"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: edCol.implicitHeight + 24
                        ColumnLayout {
                            id: edCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 10

                            Text { text: "正文字号"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny }
                            Row {
                                spacing: 5
                                Repeater {
                                    model: [{ t: "小", v: 0.9 }, { t: "标准", v: 1.0 }, { t: "大", v: 1.12 }, { t: "特大", v: 1.25 }]
                                    delegate: Rectangle {
                                        required property var modelData
                                        height: 26; radius: 7
                                        width: fsText.implicitWidth + 16
                                        color: Math.abs((settings.ep.fontScale || 1.0) - modelData.v) < 0.01
                                               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                                        border.width: 1
                                        border.color: Math.abs((settings.ep.fontScale || 1.0) - modelData.v) < 0.01 ? Theme.accent : Theme.border
                                        Text {
                                            id: fsText
                                            anchors.centerIn: parent
                                            text: modelData.t
                                            color: Math.abs((settings.ep.fontScale || 1.0) - modelData.v) < 0.01 ? Theme.accent : Theme.textTertiary
                                            font.pixelSize: Theme.fsTiny
                                        }
                                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: { bridge.setEditorPref("fontScale", modelData.v); settings.refreshPrefs() } }
                                    }
                                }
                            }

                            Text { text: "正文限宽居中（约 820px 阅读宽度）"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny }
                            AppCheck {
                                checked: settings.ep.narrow !== false
                                text: checked ? "开启限宽" : "全宽"
                                font.pixelSize: Theme.fsSmall
                                palette.text: Theme.textPrimary
                                onCheckedChanged: if (activeFocus) { bridge.setEditorPref("narrow", checked); settings.refreshPrefs() }
                            }

                            Text { text: "流式输出速度（S4 打字机/即时）"; color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny }
                            AppCheck {
                                checked: settings.ep.streamSmooth === true
                                text: checked ? "打字机（平滑逐字）" : "即时（全文直出）"
                                font.pixelSize: Theme.fsSmall
                                palette.text: Theme.textPrimary
                                onCheckedChanged: if (activeFocus) { bridge.setEditorPref("streamSmooth", checked); settings.refreshPrefs() }
                            }
                        }
                    }

                    Text {
                        text: "阅读偏好"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "阅读主题（夜间 / 羊皮纸 / 纯白）、字号、行距、字体、翻页方式都在阅读模式内「Aa 排版」面板即时调整并持久化。"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                        wrapMode: Text.Wrap
                    }

                    Item { height: 8 }
                }
            }

            // ============ 页3：系统（备份 + 快捷键） ============
            ScrollView {
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 12
                    Layout.margins: 12

                    Text {
                        text: "备份与统计"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: bkCol.implicitHeight + 24
                        ColumnLayout {
                            id: bkCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 8
                            Text { text: "项目备份"; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; font.bold: true }
                            Text {
                                text: "zip 全量备份到项目同级目录（含设定 / 大纲 / 正文 / 追踪 / 版本 / 状态）。"
                                color: Theme.textTertiary; font.family: Theme.uiFont; font.pixelSize: Theme.fsTiny
                                wrapMode: Text.Wrap; Layout.fillWidth: true
                            }
                            AppCheck {
                                id: autoBackupSwitch
                                text: checked ? "每日自动备份（打开项目时执行）" : "每日自动备份已关闭"
                                font.pixelSize: Theme.fsSmall
                                palette.text: Theme.textPrimary
                                onCheckedChanged: if (activeFocus) bridge.setAutoBackup(checked)
                            }
                            RowLayout {
                                spacing: 8
                                AppButton { text: "立即备份 zip"; kind: "primary"; height: 28; onClicked: bridge.backupProject() }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }

                    Text {
                        text: "快捷键"
                        color: Theme.textPrimary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.rCard
                        color: Theme.bgCard
                        implicitHeight: keysCol.implicitHeight + 24
                        ColumnLayout {
                            id: keysCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 8
                            Repeater {
                                model: [
                                    ["Ctrl + S", "保存章节（产生新版本 · 保存驱动）"],
                                    ["F5", "进入沉浸阅读模式"],
                                    ["Esc", "退出阅读 / 关闭对话框"],
                                    ["← / →", "阅读模式翻页（翻页模式下）"],
                                    ["Ctrl + B", "版本历史（diff / 回退）"],
                                    ["Ctrl + E", "局部改写选中段落"]
                                ]
                                delegate: RowLayout {
                                    required property var modelData
                                    spacing: 10
                                    Layout.fillWidth: true
                                    Rectangle {
                                        width: 72; height: 24; radius: 6
                                        color: Theme.bgHover
                                        border.width: 1; border.color: Theme.border
                                        Text { anchors.centerIn: parent; text: modelData[0]; color: Theme.accent; font.family: Theme.monoFont; font.pixelSize: 11 }
                                    }
                                    Text { text: modelData[1]; color: Theme.textSecondary; font.family: Theme.uiFont; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }

                    Item { height: 8 }
                }
            }
        }
    }
}
