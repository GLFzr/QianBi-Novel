import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Rectangle {
    id: row
    property int num: 0
    property string title: ""
    property string state: "queued"      // pass / writing / needs_fix / outline_ready / queued
    property int words: 0
    property string note: ""

    signal openChapter(int num)
    signal rewriteChapter(int num)
    signal rewriteChapterWithGuidance(int num, string guidance)

    width: ListView.view ? ListView.view.width : 300
    height: 46
    radius: 8
    color: mouseArea.containsMouse ? Theme.bgHover
         : state === "writing" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08)
         : state === "needs_fix" ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.05)
         : "transparent"
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
                : row.state === "outline_ready" ? "（细纲已就绪）" : "（待生成细纲）"
            color: row.state === "writing" ? Theme.accent : Theme.textPrimary
            font.family: Theme.uiFont
            font.pixelSize: Theme.fsSmall
            elide: Text.ElideRight
        }
        Text {
            Layout.alignment: Qt.AlignVCenter
            visible: text !== ""
            text: row.note !== "" ? row.note : (row.words > 0 ? row.words.toLocaleString() : "")
            color: row.state === "needs_fix" ? Theme.danger : Theme.textTertiary
            font.family: Theme.monoFont
            font.pixelSize: Theme.fsTiny
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
            if (mouse.button === Qt.LeftButton && (row.state === "pass" || row.state === "needs_fix"))
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
            text: "重写本章"
            onTriggered: row.rewriteChapter(row.num)
        }
        MenuItem {
            text: "带指导重写…"
            onTriggered: guidanceDialog.open()
        }
        MenuItem {
            text: "打开查看"
            onTriggered: row.openChapter(row.num)
        }
    }

    Dialog {
        id: guidanceDialog
        modal: true
        anchors.centerIn: parent
        width: 420
        padding: 18
        title: "带指导重写 第 " + row.num + " 章"
        background: Rectangle {
            radius: Theme.rCard
            color: Theme.bgCard
            border.width: 1
            border.color: Theme.borderStrong
        }
        header: Text {
            text: guidanceDialog.title
            color: Theme.textPrimary
            font.family: Theme.serifFont
            font.pixelSize: Theme.fsTitle
            font.bold: true
            padding: 18
        }
        contentItem: Column {
            spacing: 10
            width: parent.width
            Text {
                text: "写下你对本章的重写要求（会注入正文生成 prompt）："
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
            TextField {
                id: guidanceInput
                width: parent.width
                placeholderText: "如：这章别写死女主；打脸要写在场配角的反应；结尾钩子指向下章的拍卖会…"
                placeholderTextColor: Theme.textTertiary
                color: Theme.textPrimary
                font.family: Theme.uiFont
                font.pixelSize: Theme.fsBody
                selectByMouse: true
                background: Rectangle {
                    radius: Theme.rBtn
                    color: Theme.bgHover
                    border.width: 1
                    border.color: Theme.border
                }
            }
        }
        footer: Row {
            spacing: 8
            anchors.right: parent.right
            anchors.margins: 12
            AppButton {
                text: "取消"
                kind: "ghost"
                onClicked: guidanceDialog.close()
            }
            AppButton {
                text: "重写"
                kind: "primary"
                onClicked: {
                    row.rewriteChapterWithGuidance(row.num, guidanceInput.text)
                    guidanceInput.text = ""
                    guidanceDialog.close()
                }
            }
        }
    }
}
