import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// WizardDialog · 首启向导（封装计划 T3.5，两步轻量版）
// 步骤 1：欢迎 + 开源声明 + 数据目录说明
// 步骤 2：连接配置指引（粘贴模型 Key，即时可用）→ 完成
// ============================================================
Dialog {
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
    }
    id: wizard
    objectName: "wizardDialog"
    modal: true
    closePolicy: Popup.NoAutoClose
    width: 560
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
    padding: 18
    background: DialogBg {}
    header: Text {
        text: "欢迎使用千笔一文 Novel"
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTitle
        font.weight: Font.DemiBold
        padding: 16
    }

    property int step: 1
    // A9：三槽连接齐备与否（与桥面 _slot_readiness 同一判定）——决定「开始写作」主/次级与提示行
    property bool connAllReady: bridge.connReadySummary.every(function (r) { return r.ready })

    // ---- OB-M2：内嵌迷你连接表单（选服务商 → 贴 Key → 选模型 → 测试，不离开向导）----
    // 改的是当前第一条（出厂推荐）连接：就地补齐 Key/模型后保存，checklist 即时
    // 亮绿（connReadySummary 同源刷新）——「打开连接设置」降为深度配置的次级出口。
    property string wizConnId: ""
    property string wizName: ""
    property var wizRest: ({ temperature: 0.7, max_tokens: 8192, timeout: 300,
                             thinking: "", reasoning_effort: "" })
    property bool wizTestOk: false
    property string wizTestMsg: ""          // 空串 = 未测过

    ListModel { id: miniModels }

    function wizFillModels(idx) {
        var opts = bridge.providerOptions
        if (idx < 0 || idx >= opts.length) return
        var models = opts[idx].models || []
        var typed = miniModel.editText
        miniModels.clear()
        for (var i = 0; i < models.length; i++) miniModels.append({ "m": models[i] })
        miniModel.currentIndex = -1
        miniModel.editText = typed          // 换建议列表不打断已手填的模型名
    }

    function wizLoad() {
        var opts = bridge.connectionOptions()
        if (!opts.length) return
        var c = bridge.getConnection(opts[0].id)
        wizConnId = opts[0].id
        wizName = c.name || ""
        var prov = c.provider || "custom"
        for (var p = 0; p < bridge.providerOptions.length; p++)
            if (bridge.providerOptions[p].key === prov) miniProvider.currentIndex = p
        miniUrl.text = c.base_url || (bridge.providerOptions.length
                                      ? bridge.providerOptions[miniProvider.currentIndex].baseUrl : "")
        miniKey.text = c.api_key || ""
        miniModel.currentIndex = -1
        miniModel.editText = c.model || ""
        wizFillModels(miniProvider.currentIndex)
        wizRest = {
            "temperature": c.temperature !== undefined ? c.temperature : 0.7,
            "max_tokens": c.max_tokens || 8192,
            "timeout": c.timeout || 300,
            "thinking": c.thinking || "",
            "reasoning_effort": c.reasoning_effort || ""
        }
        wizTestMsg = ""
    }

    onOpened: wizLoad()
    Connections {
        target: bridge
        function onConnTestResult(cid, ok, msg) {
            if (cid === "__wizard__") { wizard.wizTestOk = ok; wizard.wizTestMsg = msg }
        }
    }

    contentItem: ColumnLayout {
        spacing: 12

        // ---- 步骤 1：欢迎 ----
        ColumnLayout {
            visible: wizard.step === 1
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "这是一台运行在你电脑上的 AI 网文写作台：立项 → 设定 → 大纲 → 逐章写作，每一步都可以介入和回退。"
                color: Theme.textPrimary
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                text: "· 开源软件（MIT License），免费使用\n· 你自带模型 API Key，数据全部保存在本机 ~/.qianbi_novel/\n· 写作过程中每一步都会征求你的决定（可在设置中调整介入强度）"
                color: Theme.textSecondary
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
            CheckBox {
                id: eulaCheck
                Layout.fillWidth: true
                text: "我已阅读并同意 MIT License 与隐私说明（数据不出本机，遥测默认关闭）"
                font.pixelSize: Theme.fsTiny
            }
            // A9：更新检查状态行——首启那次外网请求要有一行交代；失败静默不显
            Text {
                Layout.fillWidth: true
                visible: bridge.updateState.checking || bridge.updateState.available
                text: bridge.updateState.checking
                      ? "正在检查更新…（可随时在 设置 → 系统 关闭）"
                      : "发现新版本——稍后可在 设置 → 系统 升级，不影响现在开始写作"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }

        // ---- 步骤 2：连接配置（A9：checklist 化——两件事并列，就绪状态实时可见）----
        ColumnLayout {
            visible: wizard.step === 2
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "出门前两件事，做完就能开写：\n① 选一家服务商，粘贴 API Key；\n② 为它选一个模型（下拉有候选，或点「拉取」拿实时列表）。\n两件都做了再点「测试连接」，看到「连接正常」就绪。"
                color: Theme.textPrimary
                font.pixelSize: Theme.fsBody
                wrapMode: Text.Wrap
            }
            // A9：就绪清单——与桥面 _slot_readiness 同一判定，配好即亮绿勾
            Repeater {
                model: bridge.connReadySummary
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    Text {
                        text: modelData.ready ? "✓" : "○"
                        color: modelData.ready ? "#3a9d5f" : Theme.textTertiary
                        font.pixelSize: Theme.fsSmall
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.ready ? modelData.label + "：就绪"
                                              : modelData.label + "：" + modelData.reason
                        color: modelData.ready ? Theme.textSecondary : Theme.textTertiary
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                }
            }
            // OB-M2：迷你连接表单——四件事不离开向导完成（保存后 checklist 即时亮绿）
            Rectangle {
                Layout.fillWidth: true
                radius: 8
                color: Theme.bgCard
                border.width: 1
                border.color: Theme.border
                height: miniCol.implicitHeight + 16
                ColumnLayout {
                    id: miniCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    spacing: 6
                    Text {
                        Layout.fillWidth: true
                        text: "就地配好连接（改的是当前推荐那条，不用离开向导）："
                        color: Theme.textSecondary
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Row {
                        Layout.fillWidth: true
                        spacing: 6
                        Column {
                            spacing: 4
                            width: 128
                            Text { text: "服务商"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny }
                            AppSelect {
                                id: miniProvider
                                width: parent.width
                                model: bridge.providerOptions.map(function (o) { return o.label })
                                onActivated: function (idx) {
                                    miniUrl.text = bridge.providerOptions[idx].baseUrl
                                    wizard.wizFillModels(idx)
                                }
                            }
                        }
                        Column {
                            spacing: 4
                            width: parent.width - 134
                            Text { text: "接口地址"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny }
                            TextField {
                                id: miniUrl
                                width: parent.width
                                color: Theme.textPrimary
                                font.pixelSize: Theme.fsSmall
                                selectByMouse: true
                                background: Rectangle {
                                    radius: Theme.rBtn
                                    color: Theme.bgHover
                                    border.width: 1
                                    border.color: miniUrl.activeFocus ? Theme.accent : Theme.border
                                }
                            }
                        }
                    }
                    Row {
                        Layout.fillWidth: true
                        spacing: 6
                        Column {
                            spacing: 4
                            width: parent.width - 176
                            Text { text: "API Key"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny }
                            TextField {
                                id: miniKey
                                width: parent.width
                                echoMode: TextInput.Password
                                color: Theme.textPrimary
                                font.pixelSize: Theme.fsSmall
                                placeholderText: "sk-…"
                                placeholderTextColor: Theme.textTertiary
                                selectByMouse: true
                                background: Rectangle {
                                    radius: Theme.rBtn
                                    color: Theme.bgHover
                                    border.width: 1
                                    border.color: miniKey.activeFocus ? Theme.accent : Theme.border
                                }
                            }
                        }
                        Column {
                            spacing: 4
                            width: 170
                            Text { text: "模型（下拉候选或直接填）"; color: Theme.textTertiary; font.pixelSize: Theme.fsTiny }
                            ComboBox {
                                id: miniModel
                                width: parent.width
                                editable: true
                                model: miniModels
                                textRole: "m"
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        AppButton {
                            text: "测试连接"
                            onClicked: {
                                wizard.wizTestMsg = ""
                                bridge.testConnectionDraft({
                                    "id": "__wizard__",
                                    "name": wizard.wizName || "向导连接",
                                    "provider": bridge.providerOptions[miniProvider.currentIndex].key,
                                    "base_url": miniUrl.text,
                                    "api_key": miniKey.text,
                                    "model": miniModel.editText !== "" ? miniModel.editText
                                                                       : miniModel.currentText,
                                    "temperature": wizard.wizRest.temperature,
                                    "max_tokens": wizard.wizRest.max_tokens,
                                    "timeout": wizard.wizRest.timeout,
                                    "thinking": wizard.wizRest.thinking,
                                    "reasoning_effort": wizard.wizRest.reasoning_effort
                                })
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: "连接通但模型空会出黄牌提示（黄牌不是红牌：连接没坏，选上模型即可）"
                        }
                        AppButton {
                            objectName: "wizardSaveConnButton"
                            text: "保存这条连接"
                            kind: "primary"
                            onClicked: {
                                bridge.saveConnection({
                                    "id": wizard.wizConnId,
                                    "name": wizard.wizName || "我的连接",
                                    "provider": bridge.providerOptions[miniProvider.currentIndex].key,
                                    "base_url": miniUrl.text,
                                    "api_key": miniKey.text,
                                    "model": miniModel.editText !== "" ? miniModel.editText
                                                                       : miniModel.currentText,
                                    "temperature": wizard.wizRest.temperature,
                                    "max_tokens": wizard.wizRest.max_tokens,
                                    "timeout": wizard.wizRest.timeout,
                                    "thinking": wizard.wizRest.thinking,
                                    "reasoning_effort": wizard.wizRest.reasoning_effort
                                })
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: "保存后上方清单即时重判——三槽全绿「开始写作」自动变主按钮"
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            Layout.fillWidth: true
                            visible: wizard.wizTestMsg !== ""
                            text: (wizard.wizTestOk ? "✓ " : "✗ ") + wizard.wizTestMsg
                            color: wizard.wizTestOk
                                   ? (wizard.wizTestMsg.indexOf("⚠") === 0 ? Theme.warn : "#3a9d5f")
                                   : Theme.danger
                            font.pixelSize: Theme.fsMicro
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
            AppButton {
                text: "▶ 看 5 分钟演示（无需 Key）"
                kind: "primary"
                visible: bridge.demoAvailable
                onClicked: {
                    wizard.close()
                    bridge.setOnboarded()
                    bridge.demoStart()
                }
            }
            AppButton {
                text: "打开连接设置"
                onClicked: {
                    mainWindow.activePanel = "settings"
                    wizard.close()
                    bridge.setOnboarded()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !wizard.connAllReady
                text: "还没配好连接也能先进来看看，之后在「设置 · 连接与模型」随时可配。"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
        }

        // ---- 底部按钮 ----
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            AppButton {
                text: "跳过"
                visible: wizard.step === 1
                onClicked: { wizard.close(); bridge.setOnboarded() }
            }
            AppButton {
                text: "下一步"
                kind: "primary"
                enabled: wizard.step !== 1 || eulaCheck.checked
                onClicked: wizard.step = 2
            }
            AppButton {
                text: "开始写作"
                kind: wizard.connAllReady ? "primary" : "secondary"
                visible: wizard.step === 2
                onClicked: { wizard.close(); bridge.setOnboarded() }
            }
        }
    }
}
