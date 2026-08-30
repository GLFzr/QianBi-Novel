import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// AboutDialog · 关于（封装计划 T4.2）
// 版本/构建 · 检查更新（GitHub Releases 主通道）· 日志/数据目录
// 遥测开关（opt-in，默认关）· 开源声明
// ============================================================
Dialog {
    id: aboutDialog
    objectName: "aboutDialog"
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
        font.bold: true
        padding: 16
    }

    contentItem: ColumnLayout {
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "版本 v" + bridge.appVersion
                color: Theme.textPrimary
                font.pixelSize: Theme.fsBody
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            AppButton {
                text: updateState.hasNew ? "前往下载" : "检查更新"
                onClicked: {
                    if (updateState.hasNew) {
                        if (updateState.url !== "")
                            Qt.openUrlExternally(updateState.url)
                    } else {
                        updateState.checking = true
                        bridge.checkForUpdates(true)
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: {
                if (updateState.hasNew)
                    return "发现新版本 v" + updateState.version + (updateState.notes !== "" ? "\n" + updateState.notes : "")
                if (updateState.checking)
                    return "正在检查更新…"
                return "开源软件（MIT License）· 本地数据 · 自带模型 Key"
            }
            color: updateState.hasNew ? Theme.accent : Theme.textTertiary
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.WrapAnywhere
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // 遥测开关（opt-in，默认关；仅本地落点）
        RowLayout {
            Layout.fillWidth: true
            CheckBox {
                id: telemCheck
                text: "匿名使用统计（仅保存在本机，帮助改进；默认关闭）"
                checked: bridge.telemetryEnabled
                font.pixelSize: Theme.fsTiny
                onToggled: bridge.setTelemetryEnabled(checked)
            }
        }

        RowLayout {
            spacing: 8
            AppButton { text: "打开日志目录"; onClicked: bridge.openLogDir() }
            AppButton { text: "打开数据目录"; onClicked: bridge.openDataDir() }
            Item { Layout.fillWidth: true }
            AppButton {
                text: "关闭"
                onClicked: aboutDialog.close()
            }
        }

        Text {
            Layout.fillWidth: true
            text: "本项目基于 MIT License 开源发布。第三方组件声明见安装目录 THIRD-PARTY-LICENSES.md。"
            color: Theme.textTertiary
            font.pixelSize: 10
            wrapMode: Text.WrapAnywhere
        }
    }

    // 更新检查状态（跨 Connections 保持）
    QtObject {
        id: updateState
        property bool hasNew: false
        property bool checking: false
        property string version: ""
        property string notes: ""
        property string url: ""
    }
    Connections {
        target: bridge
        function onUpdateFound(version, notes, url) {
            updateState.hasNew = true
            updateState.checking = false
            updateState.version = version
            updateState.notes = notes
            updateState.url = url
        }
    }
    onClosed: {
        updateState.hasNew = false
        updateState.checking = false
    }
}
