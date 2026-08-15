import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."
import "components"

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1280
    height: 800
    minimumWidth: 1024
    minimumHeight: 680
    title: "千笔一文 Novel"
    color: Theme.bgPage

    readonly property var navItems: [
        { "label": "书架", "needProject": false },
        { "label": "流水线", "needProject": true },
        { "label": "章节详情", "needProject": true },
        { "label": "连接与模型", "needProject": false }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- 左侧导航 ----
        Rectangle {
            Layout.preferredWidth: 176
            Layout.fillHeight: true
            color: Theme.bgPanel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            Column {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 2

                Row {
                    spacing: 8
                    height: 44
                    Rectangle {
                        width: 28; height: 28; radius: 8
                        color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            anchors.centerIn: parent
                            text: "文"
                            color: "#1D1B17"
                            font.family: Theme.serifFont
                            font.pixelSize: 14
                            font.bold: true
                        }
                    }
                    Text {
                        text: "千笔一文"
                        color: Theme.textPrimary
                        font.family: Theme.serifFont
                        font.pixelSize: Theme.fsBody
                        font.bold: true
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle { width: parent.width - 8; height: 1; color: Theme.border; anchors.horizontalCenter: parent.horizontalCenter }
                Item { width: 1; height: 8 }

                Repeater {
                    model: mainWindow.navItems
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: 36
                        radius: 8
                        enabled: !modelData.needProject || bridge.hasProject
                        opacity: enabled ? 1.0 : 0.4
                        color: stack.currentIndex === index ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.10)
                             : navMouse.containsMouse ? Theme.bgHover : "transparent"

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: stack.currentIndex === index ? Theme.accent : Theme.textSecondary
                            font.family: Theme.uiFont
                            font.pixelSize: Theme.fsSmall
                        }
                        MouseArea {
                            id: navMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            enabled: parent.enabled
                            onClicked: stack.currentIndex = index
                        }
                    }
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                text: "千笔一文 Novel · P0"
                color: Theme.textTertiary
                font.pixelSize: Theme.fsTiny
                font.family: Theme.uiFont
            }
        }

        // ---- 主区 ----
        StackLayout {
            id: stack
            objectName: "mainStack"
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: bridge.hasProject ? 1 : 0

            Bookshelf {}
            Monitor {
                onGotoChapterDetail: stack.currentIndex = 2
            }
            ChapterDetail {
                onGotoMonitor: stack.currentIndex = 1
            }
            ConnectionsPage {}
        }
    }

    // ---- 全局 Toast ----
    Rectangle {
        id: toastBar
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: Math.min(560, toastText.implicitWidth + 48)
        height: 40
        radius: 20
        color: Theme.bgHover
        border.width: 1
        border.color: toastBar.toastLevel === "error" ? Theme.danger
                 : toastBar.toastLevel === "warn" ? Theme.accent
                 : Theme.borderStrong
        opacity: 0
        visible: opacity > 0

        property string toastLevel: "info"

        function showToast(level, msg) {
            toastBar.toastLevel = level
            toastText.text = msg
            toastAnim.restart()
        }

        Text {
            id: toastText
            anchors.centerIn: parent
            color: Theme.levelColor(toastBar.toastLevel)
            font.pixelSize: Theme.fsSmall
            font.family: Theme.uiFont
            width: Math.min(520, implicitWidth)
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }

        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toastBar; property: "opacity"; to: 1; duration: 160 }
            PauseAnimation { duration: 2600 }
            NumberAnimation { target: toastBar; property: "opacity"; to: 0; duration: 300 }
        }
    }

    Connections {
        target: bridge
        function onToast(level, msg) { toastBar.showToast(level, msg) }
        function onProjectOpened() { stack.currentIndex = 1 }
    }
}
