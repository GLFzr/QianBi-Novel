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
                if (updateState.hasNew) {
                    var s = "发现新版本 v" + updateState.version
                            + (updateState.notes !== "" ? "\n" + updateState.notes : "")
                    if (updateState.sha256 !== "")
                        s += "\n安装包 SHA-256：" + updateState.sha256
                    return s
                }
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
            Layout.fillWidth: true
            CheckBox {
                objectName: "autoCheckRow"
                text: "启动时检查更新（开机访问 GitHub 取版本清单；默认关闭）"
                checked: bridge.updateAutoCheck
                font.pixelSize: Theme.fsTiny
                onToggled: bridge.setUpdateAutoCheck(checked)
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // 升级前该知道哪些目录不会被动：安装器只覆盖程序目录
        Text {
            Layout.fillWidth: true
            text: "更新只覆盖程序目录，不会写入下面这些位置：\n书稿：" + bridge.defaultBooksRoot()
                  + "\n配置：" + bridge.dataDirPath()
            color: Theme.textTertiary
            font.pixelSize: 10
            wrapMode: Text.WrapAnywhere
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
        property string sha256: ""
    }
    Connections {
        target: bridge
        function onUpdateFound(version, notes, url, sha256) {
            updateState.hasNew = true
            updateState.checking = false
            updateState.version = version
            updateState.notes = notes
            updateState.url = url
            updateState.sha256 = sha256
        }
    }
    onClosed: {
        updateState.hasNew = false
        updateState.checking = false
        updateState.sha256 = ""
    }
}
