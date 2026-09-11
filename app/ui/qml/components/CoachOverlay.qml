import QtQuick
import QtQuick.Controls.Basic
import ".."   // Theme 单例（qmldir singleton，位于上级 qml/ 目录）

// ============================================================
// CoachOverlay · 演示引导层（0.20.0）
// 挂在 Overlay.overlay 上（z 高于弹窗）：两种模式
//  - 遮罩模式（container 为空）：四矩形围出目标挖孔，挖孔外全部吃掉点击
//    ——「其余位置按下去」；挖孔内无 MouseArea，点击天然穿透到真实控件
//  - 环式模式（container 非空，如新建项目弹窗内）：不遮罩（弹窗自带模态
//    变暗），只画高亮环 + 气泡；弹窗字段保持可点
// 气泡：小字文案 + 步骤序号 + 下一步（仅 button_next）+ 跳过演示（常驻）
// ============================================================
Item {
    id: coach
    anchors.fill: parent
    visible: false
    z: 1000

    property var payload: null
    property var targetItem: null
    property rect tRect: Qt.rect(0, 0, 0, 0)
    readonly property bool ringMode: payload ? (payload.container || "") !== "" : false
    // dim=false：回放步骤的「只环不遮」——环住原生控件但不遮罩，流式内容保持可见
    readonly property bool dimOn: payload ? (payload.dim !== false) : true

    // ---------- 桥接 ----------
    Connections {
        target: bridge
        function onDemoCoach(json) {
            coach.setData(JSON.parse(json))
        }
    }

    function setData(d) {
        payload = d
        visible = !!d && !!d.text
        ringHostActive = false
        targetItem = null
        if (!visible)
            return
        locate()
    }

    property bool ringHostActive: false

    function locate() {
        if (!payload)
            return
        var name = payload.target || ""
        targetItem = name !== "" ? demoFind(name) : null
        if (targetItem) {
            var p = targetItem.mapToItem(coach, 0, 0)
            tRect = Qt.rect(p.x - 6, p.y - 6, targetItem.width + 12, targetItem.height + 12)
        } else {
            tRect = Qt.rect(0, 0, 0, 0)
        }
        ringHostActive = ringMode
        placeBubble()
    }

    // 递归找 objectName：先内容层，再 Overlay 层（弹窗字段在那里）
    function demoFind(name) {
        return findIn(mainWindow.contentItem, name) || findIn(mainWindow.Overlay.overlay, name)
    }
    function findIn(root, name) {
        if (!root)
            return null
        if (root.objectName === name)
            return root
        for (var i = 0; i < root.children.length; i++) {
            var f = findIn(root.children[i], name)
            if (f)
                return f
        }
        return null
    }

    onWidthChanged: locate()
    onHeightChanged: locate()

    // ---------- 遮罩（遮罩模式） ----------
    component Dimmer: Rectangle {
        color: Qt.rgba(0, 0, 0, 0.72)
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.ForbiddenCursor
            onClicked: function(m) { m.accepted = true }
            onWheel: function(w) { w.accepted = true }
        }
    }
    Dimmer {
        visible: coach.visible && !coach.ringMode && coach.dimOn
        x: 0; y: 0
        width: coach.width
        height: Math.max(0, coach.tRect.y)
    }
    Dimmer {
        visible: coach.visible && !coach.ringMode && coach.dimOn
        x: 0
        y: coach.tRect.y + coach.tRect.height
        width: coach.width
        height: Math.max(0, coach.height - coach.tRect.y - coach.tRect.height)
    }
    Dimmer {
        visible: coach.visible && !coach.ringMode && coach.dimOn
        x: 0
        y: coach.tRect.y
        width: Math.max(0, coach.tRect.x)
        height: coach.tRect.height
    }
    Dimmer {
        visible: coach.visible && !coach.ringMode && coach.dimOn
        x: coach.tRect.x + coach.tRect.width
        y: coach.tRect.y
        width: Math.max(0, coach.width - coach.tRect.x - coach.tRect.width)
        height: coach.tRect.height
    }

    // 高亮环（两种模式都画）
    Rectangle {
        visible: coach.visible && coach.targetItem !== null
        x: coach.tRect.x; y: coach.tRect.y
        width: coach.tRect.width; height: coach.tRect.height
        radius: 8
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
        SequentialAnimation on opacity {
            running: coach.visible && coach.targetItem !== null
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 0.55; duration: 700 }
            NumberAnimation { from: 0.55; to: 1.0; duration: 700 }
        }
    }

    // ---------- 气泡（与 DialogBg 同语言：bgCard 主体 + borderStrong 发丝线 + 三层柔影） ----------
    Rectangle { x: bubble.x - 4;  y: bubble.y - 2;  width: bubble.width + 8;  height: bubble.height + 5
                radius: Theme.rCard + 3; color: "#2E000000"; visible: coach.visible; z: -1 }
    Rectangle { x: bubble.x - 10; y: bubble.y - 6;  width: bubble.width + 20; height: bubble.height + 13
                radius: Theme.rCard + 6; color: "#24000000"; visible: coach.visible; z: -2 }
    Rectangle {
        id: bubble
        visible: coach.visible
        width: Math.min(420, coach.width - 40)
        height: bubbleCol.implicitHeight + 24
        radius: Theme.rCard
        color: Theme.bgCard
        border.width: 1
        border.color: Theme.borderStrong

        Column {
            id: bubbleCol
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            Item {
                width: parent.width
                height: 16
                Rectangle {
                    width: stepText.width + 14
                    height: 16
                    radius: 8
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                    Text {
                        id: stepText
                        anchors.centerIn: parent
                        text: coach.payload
                              ? ("演示 " + coach.payload.step + " / " + coach.payload.total) : ""
                        color: Theme.accent
                        font.pixelSize: Theme.fsMicro
                        font.family: Theme.uiFont
                    }
                }
            }
            Text {
                width: parent.width
                text: coach.payload ? (coach.payload.text || "") : ""
                color: Theme.textPrimary
                font.pixelSize: Theme.fsSmall
                font.family: Theme.uiFont
                wrapMode: Text.Wrap
                lineHeight: 1.25
            }
            Row {
                spacing: 8
                anchors.right: parent.right
                AppButton {
                    text: "下一步 →"
                    kind: "primary"
                    height: 26
                    visible: coach.payload && coach.payload.mode === "button_next"
                    onClicked: bridge.demoNext()
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: coach.payload && coach.payload.mode === "replay" ? "▶ 演示中…" : ""
                    color: Theme.accent
                    font.pixelSize: Theme.fsTiny
                    font.family: Theme.uiFont
                }
                AppButton {
                    text: "跳过演示"
                    kind: "ghost"
                    height: 26
                    onClicked: bridge.demoSkip()
                }
            }
        }
    }

    function placeBubble() {
        if (!payload)
            return
        var bw = bubble.width
        var margin = 16
        // 目标在弹窗内时（环式模式）气泡贴窗口下沿；否则贴目标下方，放不下翻上方
        if (ringMode || !targetItem || tRect.height <= 0) {
            bubble.x = Math.max(margin, Math.min(coach.width - bw - margin,
                                                 coach.width / 2 - bw / 2))
            bubble.y = coach.height - bubble.height - 28
            return
        }
        var belowY = tRect.y + tRect.height + 14
        var aboveY = tRect.y - bubble.height - 14
        bubble.y = (belowY + bubble.height < coach.height) ? belowY
                 : (aboveY > 60 ? aboveY : Math.max(60, coach.height - bubble.height - 28))
        var cx = tRect.x + tRect.width / 2 - bw / 2
        bubble.x = Math.max(margin, Math.min(coach.width - bw - margin, cx))
    }
}
