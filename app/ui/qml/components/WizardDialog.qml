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
        font.bold: true
        padding: 16
    }

    property int step: 1

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
                wrapMode: Text.WrapAnywhere
            }
            Text {
                Layout.fillWidth: true
                text: "· 开源软件（MIT License），免费使用\n· 你自带模型 API Key，数据全部保存在本机 ~/.qianbi_novel/\n· 写作过程中每一步都会征求你的决定（可在设置中调整介入强度）"
                color: Theme.textSecondary
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.WrapAnywhere
            }
            CheckBox {
                id: eulaCheck
                Layout.fillWidth: true
                text: "我已阅读并同意 MIT License 与隐私说明（数据不出本机，遥测默认关闭）"
                font.pixelSize: Theme.fsTiny
            }
        }

        // ---- 步骤 2：连接配置 ----
        ColumnLayout {
            visible: wizard.step === 2
            spacing: 8
            Text {
                Layout.fillWidth: true
                text: "最后一步：配置你的 AI 模型连接。"
                color: Theme.textPrimary
                font.pixelSize: Theme.fsBody
                wrapMode: Text.WrapAnywhere
            }
            Text {
                Layout.fillWidth: true
                text: "点击下方按钮打开「设置 → 连接与模型」，粘贴你的 API Key（支持 DeepSeek / 通义百炼 / 任意 OpenAI 兼容接口）。填好后点「测试连接」确认可用。"
                color: Theme.textSecondary
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.WrapAnywhere
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
                text: "也可以先跳过——回到书架新建一本书时再配置。"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.WrapAnywhere
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
                kind: "primary"
                visible: wizard.step === 2
                onClicked: { wizard.close(); bridge.setOnboarded() }
            }
        }
    }
}
