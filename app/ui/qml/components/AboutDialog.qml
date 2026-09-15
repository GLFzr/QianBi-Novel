import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// AboutDialog · 关于（封装计划 T4.2）
// 版本/构建 · 更新入口（细节全在 UpdateDialog）· 日志/数据目录
// 遥测开关（opt-in，默认关）· 开源声明
// ============================================================
Dialog {
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
    }
    id: aboutDialog
    objectName: "aboutDialog"
    signal updateRequested()            // id 不跨文件作用域，让 Main.qml 去开 UpdateDialog
    modal: true
    width: 460
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
    padding: 18
    background: DialogBg {}
    header: Text {
        text: "关于 · 千笔一文 Novel"
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTitle
        font.weight: Font.DemiBold
        padding: 16
    }

    contentItem: ColumnLayout {
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "版本 v" + bridge.appVersion
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "openUpdateDialog"
                // 更新的全部状态（通道/验签/进度/离线出路）都在 UpdateDialog 一处，
                // 这里再留一份必然对不上账，所以只放入口
                text: bridge.updateAvailable ? "有新版 · 更新…" : "更新…"
                kind: bridge.updateAvailable ? "primary" : "secondary"
                onClicked: { aboutDialog.close(); aboutDialog.updateRequested() }
            }
        }
        Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "开源软件（MIT License）· 本地数据 · 自带模型 Key"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.Wrap
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // 遥测开关（opt-in，默认关；仅本地落点）
        RowLayout {
            Layout.fillWidth: true
            AppCheck {
                id: telemCheck
                text: "匿名使用统计（仅保存在本机，帮助改进；默认关闭）"
                checked: bridge.telemetryEnabled
                font.pixelSize: Theme.fsTiny
                onToggled: bridge.setTelemetryEnabled(checked)
            }
        }

        // 公测数据包（v0.18.4）：一键导出命中率/成本/质量元数据，发给我们改进程序
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            AppCheck {
                id: betaNote
                text: "公测版：我在参与公测，愿意提交匿名数据"
                checked: bridge.telemetryEnabled
                font.pixelSize: Theme.fsTiny
                onToggled: bridge.setTelemetryEnabled(checked)
            }
            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: "数据包内容：token 用量与缓存命中率、各步骤耗时、章节完成/清算计数。"
                      + "不含：书稿正文、提示词、API Key、连接配置。导出后发到公测群即可。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
            RowLayout {
                spacing: 8
                AppButton {
                    text: "导出公测数据包"
                    kind: "secondary"
                    onClicked: {
                        var r = bridge.exportBetaPack()
                        packResult.text = r
                        packResult.visible = true
                    }
                }
                AppButton {
                    text: "打开所在目录"
                    kind: "ghost"
                    onClicked: bridge.openBetaPackDir()
                }
            }
            Text {
                id: packResult
                visible: false
                Layout.fillWidth: true
                textFormat: Text.PlainText
                color: Theme.success
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // 升级前该知道哪些目录不会被动：安装器只覆盖程序目录
        Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "更新只覆盖程序目录，不会写入下面这些位置：\n书稿：" + bridge.defaultBooksRoot()
                  + "\n配置：" + bridge.dataDirPath()
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.Wrap
        }

        // L2-13/L2-17：审计痕回看 + 归档安全网入口
        Rectangle {
            Layout.fillWidth: true
            height: auditCol.implicitHeight + 20
            radius: Theme.rCard
            color: Theme.bgHover
            ColumnLayout {
                id: auditCol
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4
                Text {
                    text: "强锁审计痕（作者绕过的门都在这里可回看）"
                    color: Theme.textSecondary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsSmall
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: {
                        var fl = bridge.forcedLocksList()
                        if (fl.length === 0) return "暂无强锁记录"
                        var lines = []
                        for (var i = Math.max(0, fl.length - 8); i < fl.length; i++)
                            lines.push("第" + fl[i].num + "章 · " + fl[i].reason + " · " + fl[i].ts)
                        return lines.join("
")
                    }
                    color: Theme.textTertiary
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsMicro
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    spacing: 8
                    AppButton { text: "打开门回退归档"; onClicked: bridge.openProjDebugDir("rollback") }
                    AppButton { text: "打开 Agent 归档"; onClicked: bridge.openProjDebugDir("agent_tools") }
                    AppButton { text: "打开失败现场"; onClicked: bridge.openProjDebugDir("") }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        RowLayout {
            spacing: 8
            AppButton { text: "打开日志目录"; onClicked: bridge.openLogDir() }
            AppButton { text: "打开数据目录"; onClicked: bridge.openDataDir() }
            AppButton { text: "打开书稿目录"; onClicked: bridge.openPath(bridge.defaultBooksRoot()) }
            Item { Layout.fillWidth: true }
            AppButton {
                text: "关闭"
                onClicked: aboutDialog.close()
            }
        }

        Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "本项目基于 MIT License 开源发布。
第三方组件声明见安装目录 THIRD-PARTY-LICENSES.md 文件。"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.Wrap
        }
    }
}
