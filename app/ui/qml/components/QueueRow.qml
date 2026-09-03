import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Rectangle {
    id: row
    property int num: 0
    property string title: ""
    property string state: "queued"      // pass / writing / needs_fix / outline_ready / untracked / queued
    property int words: 0
    property string note: ""

    signal openChapter(int num)
    signal rewriteChapter(int num)
    signal requestGuidanceRewrite(int num)
    signal viewIssues(int num)
    signal viewGenConfig(int num)

    width: ListView.view ? ListView.view.width : 300
    height: 46
    radius: 8
    color: mouseArea.containsMouse ? Theme.bgHover
         : state === "writing" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08)
         : state === "needs_fix" ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.05)
         : state === "stale" ? Qt.rgba(Theme.highlightYellow.r, Theme.highlightYellow.g, Theme.highlightYellow.b, 0.06)
         : "transparent"
    border.width: mouseArea.containsMouse ? 1 : 0
    border.color: Theme.borderStrong
    opacity: state === "queued" || state === "outline_ready" ? 0.55 : 1.0

    Rectangle {
        width: 2
        height: parent.height - 14
        anchors.left: parent.left
        anchors.leftMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        radius: 1
        color: Theme.stateColor(row.state)
        visible: row.state !== "queued"
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 8
        spacing: 10

        Text {
            Layout.preferredWidth: 30
            Layout.alignment: Qt.AlignVCenter
            text: String(row.num).padStart(3, "0")
            color: row.state === "writing" ? Theme.accent : Theme.textTertiary
            font.family: Theme.monoFont
            font.pixelSize: Theme.fsTiny
        }
        Text {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            text: row.title !== "" ? row.title
                : row.state === "outline_ready" ? "（细纲已就绪）"
                : row.state === "untracked" ? "（待补写）" : "（待生成细纲）"
            color: row.state === "writing" ? Theme.accent : Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            elide: Text.ElideRight
        }
        Text {
            Layout.alignment: Qt.AlignVCenter
            Layout.maximumWidth: 180
            visible: text !== ""
            text: row.note !== "" ? row.note : (row.words > 0 ? Number(row.words).toLocaleString(Qt.locale(), 'f', 0) : "")
            color: row.state === "needs_fix" ? Theme.danger : Theme.textTertiary
            font.family: Theme.monoFont
            font.pixelSize: Theme.fsTiny
            elide: Text.ElideRight
        }
        AppBadge {
            Layout.alignment: Qt.AlignVCenter
            visible: row.state !== "outline_ready"
            text: Theme.stateLabel(row.state)
            tint: Theme.stateColor(row.state)
            pulse: row.state === "writing"
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function (mouse) {
            if (mouse.button === Qt.LeftButton && row.state !== "writing")
                row.openChapter(row.num)
            else if (mouse.button === Qt.RightButton)
                contextMenu.popup()
        }
    }
    Menu {
        id: contextMenu
        palette.window: Theme.bgCard
        palette.text: Theme.textPrimary
        MenuItem {
            text: "查看问题…"
            visible: row.state === "needs_fix"
            onTriggered: row.viewIssues(row.num)
        }
        MenuItem {
            text: "查看生成配置…"
            visible: row.state !== "queued" && row.state !== "outline_ready"
            onTriggered: row.viewGenConfig(row.num)
        }
        MenuItem {
            text: "重写本章"
            onTriggered: row.rewriteChapter(row.num)
        }
        MenuItem {
            text: "带指导重写…"
            onTriggered: row.requestGuidanceRewrite(row.num)
        }
        MenuItem {
            text: "打开查看"
            onTriggered: row.openChapter(row.num)
        }
    }
}
