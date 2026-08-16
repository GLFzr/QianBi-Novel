import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

// 设置面板：连接与模型（列表 + 紧凑表单 + 槽位绑定）
Item {
    id: settings

    property string editingId: ""
    property bool isNew: false

    ListModel { id: modelList }

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
                Column {
                    spacing: 3
                    Text {
                        text: "设置"
                        color: Theme.textPrimary
                        font.family: Theme.serifFont
                        font.pixelSize: Theme.fsTitle
                        font.bold: true
                    }
                    Text {
                        text: "连接与模型 · 任务槽位"
                        color: Theme.textTertiary
                        font.pixelSize: Theme.fsTiny
                        font.family: Theme.uiFont
                    }
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: "＋"
                    height: 28
                    onClicked: settings.startNew()
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

                Row {
                    Layout.fillWidth: true
                    spacing: 8
                    AppField {
                        id: keyField
                        width: parent.width - 60
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

                Column {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "模型名（可下拉选择或手动输入）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                    Row {
                        width: parent.width
                        spacing: 6
                        ComboBox {
                            id: modelField
                            width: parent.width - 76
                            editable: true
                            model: modelList
                            textRole: "m"
                            palette.window: Theme.bgCard
                            palette.text: Theme.textPrimary
                            palette.buttonText: Theme.textPrimary
                            background: Rectangle { radius: Theme.rBtn; color: Theme.bgHover; border.width: 1; border.color: Theme.border }
                        }
                        AppButton {
                            text: "拉取"
                            anchors.verticalCenter: parent.verticalCenter
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
                        width: (parent.width - 16) / 3
                        Text { text: "温度×10"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        AppSpinBox { id: tempSpin; width: parent.width; from: 0; to: 20; value: 7; overrideText: (tempSpin.value / 10).toFixed(1) }
                    }
                    Column {
                        spacing: 6
                        width: (parent.width - 16) / 3
                        Text { text: "max_tokens"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny; font.family: Theme.uiFont }
                        AppSpinBox { id: maxTokensSpin; width: parent.width; from: 512; to: 131072; stepSize: 1024; value: 8192 }
                    }
                    Column {
                        spacing: 6
                        width: (parent.width - 16) / 3
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
                    border.width: 1
                    border.color: Theme.border
                    height: slotCol.implicitHeight + 24
                    Column {
                        id: slotCol
                        anchors.fill: parent
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
                    }
                }

                Item { height: 20 }
            }
        }
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

    Component.onCompleted: {
        var opts = bridge.connectionOptions()
        if (opts.length > 0) startEdit(opts[0].id)
        else startNew()
    }
}
