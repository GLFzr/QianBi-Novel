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
    width: 480
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
