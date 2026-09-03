import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

// ============================================================
// UsageDialog · Token 用量统计（插件）
// 今日/本月/全部 的 tokens、调用数、成本估算 + 按模型明细
// 数据来源 ~/.qianbi_novel/usage/usage.jsonl（本地，永不上传）
// ============================================================
Dialog {
    id: usageDialog
    objectName: "usageDialog"
    modal: true
    width: 520
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.max(30, Math.round((parent.height - height) / 2)) : 0
    padding: 18
    background: DialogBg {}
    header: Text {
        text: "Token 用量统计"
        color: Theme.textPrimary
        font.family: Theme.uiFont
        font.pixelSize: Theme.fsTitle
        font.bold: true
        padding: 16
    }

    property var data: ({})

    onOpened: reload()
    function reload() {
        data = bridge.usageSummary()
    }

    function fmt(n) { return Number(n || 0).toLocaleString(Qt.locale(), 'f', 0) }

    contentItem: ColumnLayout {
        spacing: 10

        // 三档汇总卡
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: [
                    { k: "今日", d: usageDialog.data.today || {} },
                    { k: "本月", d: usageDialog.data.month || {} },
                    { k: "全部", d: usageDialog.data.all || {} }
                ]
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    height: sumCol.implicitHeight + 16
                    radius: Theme.rCard
                    color: Theme.bgCard
                    border.width: 1
                    border.color: Theme.border
                    ColumnLayout {
                        id: sumCol
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 2
                        Text { text: modelData.k; color: Theme.textTertiary; font.pixelSize: Theme.fsMicro; font.family: Theme.uiFont }
                        Text {
                            text: usageDialog.fmt((modelData.d["in"] || 0) + (modelData.d["out"] || 0)) + " tokens"
                            color: Theme.textPrimary; font.pixelSize: Theme.fsBody; font.bold: true
                        }
                        Text {
                            text: "调用 " + usageDialog.fmt(modelData.d.calls || 0) + " 次 · ≈ ¥" +
                                  (modelData.d.cost || 0).toFixed(2)
                            color: Theme.textSecondary; font.pixelSize: Theme.fsMicro
                        }
                    }
                }
            }
        }

        Text {
            text: "按模型明细（全部）"
            color: Theme.textTertiary
            font.pixelSize: Theme.fsMicro
            font.family: Theme.uiFont
        }
        ListView {
            id: modelList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(modelCount() * 44 + 8, 200)
            clip: true
            spacing: 4
            function modelCount() {
                var m = (usageDialog.data.all || {}).by_model || {}
                return Object.keys(m).length
            }
            model: {
                var m = (usageDialog.data.all || {}).by_model || {}
                return Object.keys(m).map(function (k) {
                    return { model: k, v: m[k],
                             cost: usageDialog.data.all ? 0 : 0 }
                })
            }
            delegate: Rectangle {
                required property var modelData
                width: modelList.width
                height: 40
                radius: Theme.rCard
                color: Theme.bgCard
                border.width: 1
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 8
                    Text {
                        Layout.preferredWidth: 150
                        text: modelData.model
                        color: Theme.textPrimary
                        font.pixelSize: Theme.fsSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "入 " + usageDialog.fmt(modelData.v["in"]) + " · 出 " + usageDialog.fmt(modelData.v["out"]) +
                              " · " + usageDialog.fmt(modelData.v.calls) + " 次"
                        color: Theme.textSecondary
                        font.pixelSize: Theme.fsMicro
                    }
                    Text {
                        text: {
                            var prices = {"flash": [1.0, 2.0], "mini": [1.0, 2.0]}
                            var rates = prices[modelData.model] || [2.0, 8.0]
                            var mm = modelData.model.toLowerCase()
                            for (var tag in prices) if (mm.indexOf(tag) >= 0) rates = prices[tag]
                            var c = modelData.v["in"] / 1e6 * rates[0] + modelData.v["out"] / 1e6 * rates[1]
                            return "≈ ¥" + c.toFixed(2)
                        }
                        color: Theme.textSecondary
                        font.pixelSize: Theme.fsMicro
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: "数据仅保存在本机 ~/.qianbi_novel/usage/usage.jsonl。成本为按模型费率的估算值（可在配置中覆盖费率），非账单。"
            color: Theme.textTertiary
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            AppButton { text: "刷新"; onClicked: usageDialog.reload() }
            Item { Layout.fillWidth: true }
            AppButton { text: "关闭"; onClicked: usageDialog.close() }
        }
    }
}
