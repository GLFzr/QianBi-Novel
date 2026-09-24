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
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.durNormal; easing: Theme.easeOut }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.durFast }
    }
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
        font.weight: Font.DemiBold
        padding: 16
    }

    property var data: ({})

    // U-20：按模型行数据（柱状图与明细共用；data 变更即重算）
    readonly property var modelRows: {
        var m = (data.all || {}).by_model || {}
        var rows = []
        for (var k in m) rows.push({ model: k, v: m[k] })
        return rows
    }
    // 全部模型 token 总量（柱高占比分母；防零除）
    readonly property int totalTokens: {
        var t = 0
        for (var i = 0; i < modelRows.length; i++)
            t += (modelRows[i].v["in"] || 0) + (modelRows[i].v["out"] || 0)
        return t
    }

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
            visible: usageDialog.modelRows.length > 0
            text: "按模型明细（全部）"
            color: Theme.textTertiary
            font.pixelSize: Theme.fsMicro
            font.family: Theme.uiFont
        }

        // U-20：用量柱状图（在 Dialog 内、非 delegate：柱体走 accent→accentSoft 渐变）
        // 竖柱高度 = 该模型 token 总量占全部的比例；hover 出精确数值
        Rectangle {
            visible: usageDialog.modelRows.length > 0
            Layout.fillWidth: true
            height: 110
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.border
            clip: true

            Row {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6
                Repeater {
                    model: usageDialog.modelRows
                    delegate: Item {
                        required property var modelData
                        width: parent.width / Math.max(1, usageDialog.modelRows.length) - 6
                        height: parent.height

                        // 柱体：顶部 accent → 底部 accentSoft 垂直渐变
                        Rectangle {
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 18
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.max(10, parent.width - 12)
                            height: Math.max(3, (parent.height - 26)
                                             * ((modelData.v["in"] || 0) + (modelData.v["out"] || 0))
                                             / Math.max(1, usageDialog.totalTokens))
                            radius: Theme.rSm
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: Theme.accent }
                                GradientStop { position: 1.0; color: Theme.accentSoft }
                            }
                        }
                        // 柱底模型名（非数字，按红线不用 fsMicro）
                        Text {
                            anchors.bottom: parent.bottom
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width
                            text: modelData.model
                            color: Theme.textTertiary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsTiny
                            elide: Text.ElideMiddle
                            horizontalAlignment: Text.AlignHCenter
                        }
                        // hover 命中域取整列（柱体细，小目标难点中）
                        MouseArea {
                            id: usageBarHot
                            anchors.fill: parent
                            hoverEnabled: true
                            ToolTip.visible: usageBarHot.containsMouse
                            ToolTip.text: modelData.model
                                          + " · 入 " + usageDialog.fmt(modelData.v["in"])
                                          + " · 出 " + usageDialog.fmt(modelData.v["out"])
                                          + " · " + usageDialog.fmt(modelData.v.calls) + " 次"
                                          + " · 占 " + Math.round(((modelData.v["in"] || 0) + (modelData.v["out"] || 0))
                                              / Math.max(1, usageDialog.totalTokens) * 100) + "%"
                        }
                    }
                }
            }
        }

        // U-20：空数据态（从未有用量记录时不再留一块死黑）
        AppEmptyState {
            visible: usageDialog.modelRows.length === 0
            Layout.fillWidth: true
            iconName: "inbox"
            title: "还没有用量记录"
            hint: "发起一次写作 / 扫描后，这里会按模型显示 token 用量柱状图"
        }

        ListView {
            id: modelList
            visible: usageDialog.modelRows.length > 0
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
            text: "数据仅保存在本机 ~/.qianbi_novel/usage/usage.jsonl。上方逐行成本按**默认费率**估算（config.usage_prices 的覆盖只对汇总统计生效，不改这里的行估算），非账单。"
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
