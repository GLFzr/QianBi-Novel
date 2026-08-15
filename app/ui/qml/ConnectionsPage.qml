import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// ============================================================
// 连接与模型（左列表 + 右卡片化表单 + 槽位绑定）
// ============================================================
RowLayout {
    id: connPage
    spacing: 0

    property string editingId: ""
    property bool isNew: false

    function startNew() {
        editingId = ""
        isNew = true
        nameField.text = ""
        providerCombo.currentIndex = 0
        urlField.text = bridge.providerOptions[0].baseUrl
        keyField.text = ""
        modelField.text = ""
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
        modelField.text = c.model || ""
        tempSpin.value = Math.round((c.temperature !== undefined ? c.temperature : 0.7) * 10)
        maxTokensSpin.value = c.max_tokens || 8192
        timeoutSpin.value = c.timeout || 300
        var th = c.thinking || ""
        thinkingModeCombo.currentIndex = th === "disabled" ? 1 : (th === "enabled" ? 2 : 0)
        var ef = c.reasoning_effort || ""
        effortCombo.currentIndex = ef === "low" ? 1 : (ef === "high" ? 2 : (ef === "max" ? 3 : 0))
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

    // ---- 左：连接列表 ----
    Rectangle {
        Layout.preferredWidth: 300
        Layout.fillHeight: true
        color: Theme.bgPanel
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "连接"
                    color: Theme.textSecondary
                    font.pixelSize: Theme.fsSmall
                    font.family: Theme.uiFont
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: "＋ 新建"
                    height: 26
                    onClicked: connPage.startNew()
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: bridge.connectionModelProp
                spacing: 6
                clip: true

                delegate: Rectangle {
                    required property string cid
                    required property string name
                    required property string model
                    required property string provider
                    required property string slots
                    required property int index
                    width: ListView.view.width
                    height: 64
                    radius: 10
                    color: connPage.editingId === cid && !connPage.isNew ? Theme.bgHover : "transparent"
                    border.width: 1
                    border.color: connPage.editingId === cid && !connPage.isNew ? Theme.accent : Theme.border

                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 3
                        Row {
                            spacing: 6
                            Text {
                                text: name
                                color: Theme.textPrimary
                                font.pixelSize: Theme.fsBody
                                font.family: Theme.uiFont
                                font.bold: true
                                elide: Text.ElideRight
                                width: Math.min(160, parent.parent.width - 60)
                            }
                            AppBadge {
                                visible: slots !== ""
                                text: slots
                                tint: Theme.info
                            }
                        }
                        Row {
                            spacing: 8
                            Text {
                                text: model
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.monoFont
                                elide: Text.ElideRight
                                width: 180
                            }
                            Text {
                                visible: provider !== ""
                                text: "· " + provider
                                color: Theme.textTertiary
                                font.pixelSize: Theme.fsTiny
                                font.family: Theme.uiFont
                            }
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: connPage.startEdit(cid)
                    }
                }
            }
        }
    }

    // ---- 右：编辑表单 ----
    ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 14

            ColumnLayout {
                Layout.margins: 20
                Layout.maximumWidth: 620
                Layout.preferredWidth: 620
                Layout.alignment: Qt.AlignHCenter
                spacing: 14

                // 标题
                Text {
                    text: connPage.isNew ? "新建连接" : "编辑连接"
                    color: Theme.textPrimary
                    font.pixelSize: Theme.fsTitle
                    font.family: Theme.serifFont
                    font.bold: true
                }

                // ---- 卡片：连接信息 ----
                Rectangle {
                    Layout.fillWidth: true
                    height: connInfoCol.implicitHeight + 32
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        id: connInfoCol
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 12

                        Text {
                            text: "连接信息"
                            color: Theme.textSecondary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }

                        Row {
                            width: parent.width
                            spacing: 10
                            AppField { id: nameField; width: parent.width / 2 - 5; label: "名称"; placeholder: "如：OpenCode Go Flash" }
                            Column {
                                spacing: 6
                                width: parent.width / 2 - 5
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
                        }
                        Text {
                            width: parent.width
                            text: bridge.providerOptions[providerCombo.currentIndex].hint
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                            wrapMode: Text.Wrap
                        }

                        AppField { id: urlField; width: parent.width; label: "Base URL"; placeholder: "https://api.deepseek.com" }

                        Row {
                            width: parent.width
                            spacing: 8
                            AppField {
                                id: keyField
                                width: parent.width - 70
                                label: "API Key"
                                echoMode: showKey.checked ? TextInput.Normal : TextInput.Password
                                placeholder: "sk-…"
                            }
                            AppButton {
                                id: showKey
                                text: showKey.checked ? "隐藏" : "显示"
                                anchors.bottom: parent.bottom
                                checkable: true
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 8
                            AppField { id: modelField; width: parent.width - 110; label: "模型名"; placeholder: "deepseek-v4-flash" }
                            AppButton {
                                text: "拉取列表"
                                anchors.bottom: parent.bottom
                                onClicked: {
                                    if (connPage.editingId && !connPage.isNew) bridge.fetchModels(connPage.editingId)
                                    else bridge.showToast("warn", "请先保存连接再拉取模型列表")
                                }
                            }
                        }
                    }
                }

                // ---- 卡片：模型参数 ----
                Rectangle {
                    Layout.fillWidth: true
                    height: paramCol.implicitHeight + 32
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        id: paramCol
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 12

                        Text {
                            text: "模型参数"
                            color: Theme.textSecondary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                        }

                        Row {
                            width: parent.width
                            spacing: 10
                            Column {
                                spacing: 6
                                width: (parent.width - 20) / 3
                                Text { text: "temperature ×10"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                                AppSpinBox {
                                    id: tempSpin; width: parent.width; from: 0; to: 20; value: 7
                                    overrideText: (tempSpin.value / 10).toFixed(1)
                                }
                            }
                            Column {
                                spacing: 6
                                width: (parent.width - 20) / 3
                                Text { text: "max_tokens"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                                AppSpinBox {
                                    id: maxTokensSpin; width: parent.width; from: 512; to: 131072; stepSize: 1024; value: 8192
                                }
                            }
                            Column {
                                spacing: 6
                                width: (parent.width - 20) / 3
                                Text { text: "timeout（秒）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                                AppSpinBox {
                                    id: timeoutSpin; width: parent.width; from: 30; to: 3600; stepSize: 30; value: 300
                                }
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 10
                            Column {
                                spacing: 6
                                width: (parent.width - 10) / 2
                                Text { text: "思考模式"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                                ComboBox {
                                    id: thinkingModeCombo
                                    width: parent.width
                                    model: ["默认（跟随模型）", "禁用", "启用"]
                                    palette.window: Theme.bgCard
                                    palette.text: Theme.textPrimary
                                    palette.buttonText: Theme.textPrimary
                                    background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                                }
                            }
                            Column {
                                spacing: 6
                                width: (parent.width - 10) / 2
                                Text { text: "思考强度（启用时生效）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
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
                        Text {
                            width: parent.width
                            text: "思考模式「启用」发送 thinking={type:enabled}，思考强度作为顶层 reasoning_effort（DeepSeek V4 系 low/high/max）。启用思考会消耗大量输出预算，长正文任务请调大 max_tokens（≥32768）。"
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                            wrapMode: Text.Wrap
                        }
                    }
                }

                // ---- 卡片：操作 ----
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppButton {
                        text: "测试连接"
                        onClicked: bridge.testConnectionDraft({
                            "id": connPage.editingId || "__draft__",
                            "name": nameField.text,
                            "provider": bridge.providerOptions[providerCombo.currentIndex].key,
                            "base_url": urlField.text,
                            "api_key": keyField.text,
                            "model": modelField.text,
                            "temperature": tempSpin.value / 10,
                            "max_tokens": maxTokensSpin.value,
                            "timeout": timeoutSpin.value,
                            "thinking": connPage.currentThinking(),
                            "reasoning_effort": connPage.currentEffort()
                        })
                    }
                    AppButton {
                        text: connPage.isNew ? "创建连接" : "保存修改"
                        kind: "primary"
                        onClicked: {
                            bridge.saveConnection({
                                "id": connPage.editingId,
                                "name": nameField.text || "未命名连接",
                                "provider": bridge.providerOptions[providerCombo.currentIndex].key,
                                "base_url": urlField.text,
                                "api_key": keyField.text,
                                "model": modelField.text,
                                "temperature": tempSpin.value / 10,
                                "max_tokens": maxTokensSpin.value,
                                "timeout": timeoutSpin.value,
                                "thinking": connPage.currentThinking(),
                                "reasoning_effort": connPage.currentEffort()
                            })
                            connPage.isNew = false
                        }
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: "删除"
                        kind: "danger"
                        enabled: !connPage.isNew && connPage.editingId !== ""
                        onClicked: { bridge.deleteConnection(connPage.editingId); connPage.startNew() }
                    }
                }

                // ---- 卡片：任务槽位绑定 ----
                Rectangle {
                    Layout.fillWidth: true
                    height: slotCol.implicitHeight + 32
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        id: slotCol
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10

                        Text {
                            text: "任务槽位绑定"
                            color: Theme.textPrimary
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.uiFont
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: "写作槽负责正文与设定（建议高质量模型）；辅助槽负责细纲/摘要/追踪（建议快速低价模型）；审校槽负责一致性检查"
                            color: Theme.textTertiary
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.uiFont
                            wrapMode: Text.Wrap
                        }

                        Repeater {
                            model: [
                                { "slot": "writing", "label": "写作槽" },
                                { "slot": "helper", "label": "辅助槽" },
                                { "slot": "review", "label": "审校槽" }
                            ]
                            delegate: Row {
                                width: parent.width
                                spacing: 12
                                Text {
                                    width: 56
                                    text: modelData.label
                                    color: Theme.textSecondary
                                    font.pixelSize: Theme.fsSmall
                                    font.family: Theme.uiFont
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                ComboBox {
                                    id: slotCombo
                                    width: parent.width - 80
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
                    }
                }
            }
        }
    }

    Connections {
        target: bridge
        function onModelsFetched(cid, models) {
            if (models.length > 0) {
                modelField.text = models[0]
                bridge.showToast("ok", "拉取到 " + models.length + " 个模型，已填入第一个，可手动修改")
            } else {
                bridge.showToast("warn", "未拉取到模型（接口不支持 /models 或连接失败）")
            }
        }
        function onConnTestResult(cid, ok, msg) {
            bridge.showToast(ok ? "ok" : "error", msg)
        }
    }

    Component.onCompleted: {
        var opts = bridge.connectionOptions()
        if (opts.length > 0) startEdit(opts[0].id)
        else startNew()
    }
}
