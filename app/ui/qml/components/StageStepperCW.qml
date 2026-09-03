import QtQuick
import QtQuick.Controls.Basic
import ".."

// ============================================================
// StageStepperCW · 共写档六卡导航（创建项目→核心设定→剧情总大纲→世界书正则→单元细纲→正文写作）
// 已到达的阶段可点击回看（编辑器载入对应产物）；未来阶段禁用。
// ============================================================
Row {
    id: stepperCW
    property var cards: bridge.cwStageCards
    spacing: 6

    Repeater {
        model: stepperCW.cards
        delegate: Rectangle {
            required property var modelData
            required property int index
            width: stepperCW.width / Math.max(1, stepperCW.cards.length) - 5
            height: 30
            radius: Theme.rBtn
            color: modelData.status === "active" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                 : modelData.status === "done" ? Theme.bgCard : Theme.bgLog
            border.width: 1
            border.color: modelData.status === "active" ? Theme.accent : Theme.border
            Text {
                anchors.centerIn: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                width: parent.width - 8
                text: (modelData.status === "done" ? "✓ " : modelData.status === "active" ? "● " : "") + modelData.label
                color: modelData.status === "active" ? Theme.accent
                     : modelData.status === "done" ? Theme.textSecondary : Theme.textTertiary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsMicro
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
            }
            MouseArea {
                id: cardHot
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                enabled: modelData.status !== "pending"
                onClicked: bridge.selectCwStage(modelData.key)
            }
            ToolTip.visible: cardHot.containsMouse && modelData.detail !== ""
            ToolTip.text: modelData.detail
        }
    }
}
