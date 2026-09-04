import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

// ============================================================
// UpdateDialog · 更新面板
// 四条出路同屏，因为「连不上 GitHub」不是一个错误提示能打发的事：
//   ① 在线一键（验签清单 → 下载 → 校验 → 退出并拉起安装器）
//   ② 打开发布页 / 复制直链 / 核对 SHA-256
//   ③ 导入离线清单（别人拷来的 1KB JSON）
//   ④ 选择本机已有的安装包（对完哈希才给安装按钮）
// 纪律：未过验签的清单只能被**显示**，任何下载与执行都不许被它触发。
// ============================================================
Dialog {
    id: root
    objectName: "updateDialog"
    modal: true
    width: 540
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
    padding: 16
    background: DialogBg {}
    header: Text {
        text: "更新 · 千笔一文 Novel"
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTitle
        font.bold: true
        padding: 4
    }

    readonly property var st: bridge.updateState
    readonly property var cfgs: st.settings || ({})
    readonly property var dl: st.download || ({})
    readonly property var pkg: st.package || ({})
    readonly property string state: String(st.state || "")
    readonly property bool hasNew: st.hasNew === true
    readonly property bool verified: st.verified === true
    readonly property bool canInstall: st.canInstall === true
    readonly property bool downloading: dl.active === true
    readonly property bool busy: bridge.updateBusy === true
    // 装完就走人的动作不是一般的按钮：点第一下只把「确认」问出来
    property bool armedInstall: false
    onClosed: armedInstall = false

    function mb(bytes) {
        var n = Number(bytes) || 0
        return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.round(n / 1024) + " KB"
    }
    function patch(obj) { bridge.setUpdateSettings(JSON.stringify(obj)) }

    contentItem: ColumnLayout {
        spacing: 10

        // ---- ① 现状一行看清 ----
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "本机 v" + String(st.localVersion || "")
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                font.bold: true
            }
            AppBadge {
                visible: root.hasNew
                text: "可更新 v" + String(st.version || "") + (root.verified ? "" : " · 未验签")
                tint: root.verified ? Theme.accent : Theme.warn
            }
            AppBadge {
                visible: root.state === "latest"
                text: "已是最新"
                tint: Theme.success
            }
            AppBadge {
                visible: root.state === "failed" || (root.state === "" && !root.hasNew)
                text: root.state === "failed" ? "没查到" : "还没查过"
                tint: root.state === "failed" ? Theme.warn : Theme.muted
            }
            Item { Layout.fillWidth: true }
            AppButton {
                text: root.busy ? "进行中…" : (root.state === "" ? "检查更新" : "重新检查")
                enabled: !root.busy
                kind: "ghost"
                onClicked: bridge.checkForUpdates(true)
            }
        }
        Text {
            visible: root.busy
            Layout.fillWidth: true
            text: st.checking === true
                    ? "正在逐条通道取版本清单（GitHub 被挡时会一条一条试，最多 25 秒）"
                    : "正在下载或校验…"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsTiny
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- ② 有新版：说什么、可不可信、能不能装 ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            visible: root.hasNew

            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText          // 清单是外部输入，不许它用 HTML 伪造本对话框
                text: "v" + String(st.version || "") + " · " + String(st.notes || "（清单里没有说明）")
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
            RowLayout {
                spacing: 6
                Text {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: root.verified
                          ? "清单验签通过（" + String(st.verifyReason || "") + "）· 来源通道："
                            + String(st.channelLabel || "")
                          : "⚠ " + String(st.verifyReason || "清单未通过验签")
                            + "；下面这些数字没人背书，只能自己核对。"
                    color: root.verified ? Theme.textTertiary : Theme.warn
                    font.family: Theme.uiFont
                    font.pixelSize: Theme.fsTiny
                    wrapMode: Text.Wrap
                }
            }
            Text {
                visible: !root.canInstall && String(st.whyNotInstall || "") !== ""
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(st.whyNotInstall)
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
        }

        // ---- ③ 没查到：把每条通道的死法列出来（用户据此决定配代理还是走离线）----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            visible: root.state === "failed"

            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: "所有通道都没取到清单"
                      + (String(st.proxyLabel || "") !== "" ? "（本次经路：" + String(st.proxyLabel) + "）" : "")
                      + "。是哪一层断了，看下面："
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: String(st.errors || "").replace(/\n/g, "\n· ")
                      + (String(st.errors || "") !== "" ? "" : "（没有错误记录）")
                color: Theme.textTertiary
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                text: "连不上 GitHub 时：在「设置 · 系统」里换个更新源或填代理，或者用下面两条离线出路。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
        }

        // ---- ④ 主操作：下载 / 安装 / 打开链接 ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            ThinProgress {
                Layout.fillWidth: true
                visible: root.downloading || Number(root.dl.done) > 0
                value: Number(root.dl.total) > 0 ? Math.min(1, Number(root.dl.done) / Number(root.dl.total)) : 0
            }
            Text {
                visible: Number(root.dl.done) > 0 || root.downloading
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: (root.downloading
                        ? "下载中 " + root.mb(root.dl.done) + (Number(root.dl.total) > 0 ? " / " + root.mb(root.dl.total) : "")
                        : (String(root.dl.reason || "") !== "" ? "上次下载没成：" + String(root.dl.reason)
                                                              : "已下载 " + root.mb(root.dl.done)))
                      + (String(root.dl.path || "") !== "" ? "\n存放位置：" + String(root.dl.path) : "")
                color: String(root.dl.reason || "") !== "" && !root.downloading ? Theme.warn : Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                AppButton {
                    visible: root.canInstall && root.pkg.ok !== true && !root.downloading
                    text: "下载并校验 v" + String(st.version || "")
                    kind: "primary"
                    iconName: "update"
                    onClicked: bridge.startUpdateDownload()
                }
                AppButton {
                    visible: root.downloading
                    text: "取消下载"
                    kind: "ghost"
                    onClicked: bridge.cancelUpdateDownload()
                }
                AppButton {
                    // 校验通过的包 + 验签通过的清单 + 安装版，三者齐了才让这个按钮存在
                    visible: root.canInstall && root.pkg.ok === true
                    text: root.armedInstall ? "确认退出并安装（未保存草稿会保留）"
                                            : "立即安装 v" + String(st.version || "")
                    kind: root.armedInstall ? "danger" : "primary"
                    onClicked: {
                        if (!root.armedInstall) { root.armedInstall = true; return }
                        bridge.installUpdateNow()
                    }
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    visible: String(st.url || "") !== ""
                    text: "打开发布页"
                    kind: "ghost"
                    onClicked: bridge.openUpdateUrl(String(st.url || ""))
                }
                AppButton {
                    visible: String(st.url || "") !== ""
                    text: "复制直链"
                    kind: "ghost"
                    onClicked: bridge.copyText(String(st.url || ""))
                }
            }
            Text {
                Layout.fillWidth: true
                visible: String(st.sha256 || "") !== ""
                textFormat: Text.PlainText
                text: "安装包 SHA-256：" + String(st.sha256 || "") +
                      "\n自己下的包可以点下面「选择本机安装包」让程序比对，也可以手工核对这一串。"
                color: Theme.textTertiary
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- ⑤ 离线出路：连不上也能更新的那两条 ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: "离线更新（一点网络都不用）"
                color: Theme.textSecondary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsSmall
                font.bold: true
            }
            Text {
                Layout.fillWidth: true
                text: "在能上网的设备上下载这两样，拷到本机：latest.json（约 1KB）和 setup.exe。"
                      + "先导入清单，再选安装包，两边 SHA-256 对上才会出现安装按钮。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.Wrap
            }
            RowLayout {
                spacing: 8
                AppButton {
                    text: String(st.channel || "") === "file" ? "重新导入清单…" : "导入清单文件…"
                    kind: "secondary"
                    onClicked: manifestDialog.open()
                }
                AppButton {
                    text: "选择本机安装包…"
                    kind: "secondary"
                    onClicked: packageDialog.open()
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: "打开下载目录"
                    kind: "ghost"
                    onClicked: bridge.openPath(bridge.updateDownloadPath())
                }
            }
            Text {
                visible: String(root.pkg.reason || "") !== "" || root.pkg.ok === true
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: root.pkg.ok === true
                      ? "SHA-256 命中：" + String(root.pkg.path || "")
                      : "校验没过：" + String(root.pkg.reason || "")
                        + "\n清单里写的：" + String(root.pkg.expected || "")
                        + "\n这个文件的：" + String(root.pkg.actual || "")
                color: root.pkg.ok === true ? Theme.success : Theme.warn
                font.family: Theme.monoFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- ⑥ 通道设置：镜像与代理就放在失败信息的正下方，看得见才有人配 ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            AppCheck {
                objectName: "autoCheckRow"
                text: "启动时自动检查（只下载 1KB 公开版本清单，不上传任何内容）"
                checked: root.cfgs.autoCheck === true
                font.pixelSize: Theme.fsTiny
                onToggled: root.patch({ auto_check: checked })
            }
            Text {
                objectName: "autoCheckNotice"
                visible: root.cfgs.autoCheck === true && root.cfgs.autoCheckChosen !== true
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: "这一版起自动检查默认是开的（旧版本默认关）：开机后后台下载一份 1KB 的公开版本清单，"
                      + "不上传任何内容，也不碰你的书稿和 Key。取消勾选就彻底关掉，这个提示也不会再出现。"
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 6

                AppField {
                    Layout.fillWidth: true
                    label: "自定义更新源（镜像上的 latest.json，填了排第一条试）"
                    placeholder: "https://mirror.example.com/qianbi/latest.json"
                    text: String(root.cfgs.customUrl || "")
                    onEditingFinished: root.patch({ custom_url: text })
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text {
                        text: "代理"
                        color: Theme.textTertiary
                        font.family: Theme.uiFont
                        font.pixelSize: Theme.fsTiny
                    }
                    AppSelect {
                        id: proxySelect
                        Layout.preferredWidth: 150
                        model: ["跟随系统", "跟随环境变量", "不使用代理", "自定义"]
                        property var keys: ["system", "env", "none", "custom"]
                        currentIndex: Math.max(0, keys.indexOf(String(root.cfgs.proxyMode || "system")))
                        onActivated: function (i) {
                            root.patch({ proxy_mode: keys[Math.max(0, Math.min(3, i))] })
                        }
                    }
                    AppField {
                        Layout.fillWidth: true
                        visible: String(root.cfgs.proxyMode || "") === "custom"
                        placeholder: "127.0.0.1:7897"
                        text: String(root.cfgs.proxyUrl || "")
                        onEditingFinished: root.patch({ proxy_url: text })
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: "系统代理走 PAC 自动脚本时应用解析不了，需要手动填地址。"
                      + "配了代理却连不上时会自动再用直连试一遍——陈旧代理配置不该挡死更新。"
                color: Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        Text {
            Layout.fillWidth: true
            text: "升级只覆盖程序目录，不会写入：书稿 " + bridge.defaultBooksRoot()
                  + " · 配置 " + bridge.dataDirPath()
                  + "\n安装包没有代码签名证书，双击后 Windows 会弹蓝底「Windows 已保护你的电脑」："
                  + "那是缺证书，不是文件坏了。点「更多信息」→「仍要运行」继续；"
                    + "不确定就先对一下上面的 SHA-256，跟这里列的一致就是我发布的那个文件。"
            color: Theme.textTertiary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AppButton { text: "关闭"; kind: "ghost"; onClicked: root.close() }
        }
    }

    FileDialog {
        id: manifestDialog
        objectName: "updateManifestDialog"
        title: "导入版本清单 latest.json"
        nameFilters: ["JSON 清单 (*.json)", "所有文件 (*)"]
        onAccepted: bridge.importManifestFile(String(selectedFile))
    }
    FileDialog {
        id: packageDialog
        objectName: "updatePackageDialog"
        title: "选择已下载的安装包"
        nameFilters: ["安装程序 (*.exe)", "所有文件 (*)"]
        onAccepted: bridge.checkLocalPackage(String(selectedFile))
    }
}
