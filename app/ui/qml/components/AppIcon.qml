import QtQuick
import ".."

// ============================================================
// AppIcon · 线性图标系统（ZCode 风格：1.5px 描边、方正网格、无填充）
// 用 Canvas 矢量绘制，随 color/size 换色，替代旧字符图标
// ============================================================
Canvas {
    id: icon
    property string name: ""
    property color color: Theme.textSecondary
    property real stroke: 1.6
    property int size: 18

    width: size
    height: size
    antialiasing: true

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.clearRect(0, 0, width, height)
        var s = width
        ctx.lineWidth = stroke * (s / 18.0)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.strokeStyle = color.toString()

        function p() { ctx.beginPath() }
        function mv(x, y) { ctx.moveTo(x * s, y * s) }
        function ln(x, y) { ctx.lineTo(x * s, y * s) }
        function arc(x, y, r, a0, a1) { ctx.arc(x * s, y * s, r * s, a0, a1) }
        function rect(x, y, w, h, r) { ctx.roundedRect(x * s, y * s, w * s, h * s, (r || 0) * s) }
        function stroke2() { ctx.stroke() }

        switch (name) {
        case "shelf":  // 书架：两本竖书
            p(); mv(.28, .22); ln(.28, .78); stroke2()
            p(); mv(.72, .22); ln(.72, .78); stroke2()
            p(); mv(.28, .32); ln(.5, .26); mv(.28, .68); ln(.5, .74); stroke2()
            p(); mv(.72, .32); ln(.5, .26); mv(.72, .68); ln(.5, .74); stroke2()
            break
        case "play":  // 流水线：三角播放
            p(); mv(.32, .24); ln(.70, .5); ln(.32, .76); ctx.closePath(); stroke2()
            break
        case "chapters":  // 章节：三行列表
            p(); mv(.24, .3); ln(.76, .3); mv(.24, .5); ln(.76, .5); mv(.24, .7); ln(.76, .7); stroke2()
            p(); mv(.14, .3); ln(.14, .3); ctx.arc(.14 * s, .3 * s, 1.2 * ctx.lineWidth, 0, 6.3); ctx.fillStyle = color.toString(); ctx.fill()
            p(); mv(.14, .5); ctx.arc(.14 * s, .5 * s, 1.2 * ctx.lineWidth, 0, 6.3); ctx.fill()
            p(); mv(.14, .7); ctx.arc(.14 * s, .7 * s, 1.2 * ctx.lineWidth, 0, 6.3); ctx.fill()
            break
        case "notes":  // 笔记：方纸+笔
            p(); rect(.2, .16, .48, .68, .06); stroke2()
            p(); mv(.32, .36); ln(.56, .36); mv(.32, .5); ln(.56, .5); mv(.32, .64); ln(.46, .64); stroke2()
            p(); mv(.6, .72); ln(.82, .38); mv(.66, .78); ln(.9, .58); stroke2()
            break
        case "settings":  // 设置：圆+辐条
            p(); arc(.5, .5, .2, 0, 6.3); stroke2()
            for (var i = 0; i < 8; i++) {
                var a = i * Math.PI / 4
                p()
                mv(.5 + Math.cos(a) * .32, .5 + Math.sin(a) * .32)
                ln(.5 + Math.cos(a) * .42, .5 + Math.sin(a) * .42)
                stroke2()
            }
            break
        case "log":  // 日志：终端框+线
            p(); rect(.16, .2, .68, .6, .08); stroke2()
            p(); mv(.3, .42); ln(.42, .54); ln(.3, .66); stroke2()
            p(); mv(.52, .66); ln(.7, .66); stroke2()
            break
        case "reader":  // 阅读：书本
            p(); mv(.5, .26); ctx.bezierCurveTo(.4 * s, .18 * s, .24 * s, .18 * s, .18 * s, .24 * s); ln(.18, .76); ctx.bezierCurveTo(.24 * s, .7 * s, .4 * s, .7 * s, .5 * s, .78 * s); stroke2()
            p(); mv(.5, .26); ctx.bezierCurveTo(.6 * s, .18 * s, .76 * s, .18 * s, .82 * s, .24 * s); ln(.82, .76); ctx.bezierCurveTo(.76 * s, .7 * s, .6 * s, .7 * s, .5 * s, .78 * s); stroke2()
            break
        case "save":  // 保存：软盘
            p(); rect(.18, .18, .64, .64, .08); stroke2()
            p(); rect(.32, .18, .36, .24, 0); stroke2()
            p(); rect(.32, .52, .36, .3, 0); stroke2()
            break
        case "history":  // 版本：时钟回环
            p(); arc(.5, .5, .3, .6, 5.8); stroke2()
            p(); mv(.5, .32); ln(.5, .52); ln(.66, .6); stroke2()
            break
        case "export":  // 导出：托盘上箭头
            p(); mv(.5, .16); ln(.5, .58); mv(.34, .32); ln(.5, .16); ln(.66, .32); stroke2()
            p(); mv(.2, .66); ln(.2, .82); ln(.8, .82); ln(.8, .66); stroke2()
            break
        case "scan":  // 扫描：放大镜+波
            p(); arc(.44, .44, .22, 0, 6.3); stroke2()
            p(); mv(.6, .6); ln(.78, .78); stroke2()
            p(); mv(.34, .44); ln(.42, .44); mv(.46, .38); ln(.46, .5); mv(.5, .42); ln(.54, .42); stroke2()
            break
        case "spark":  // AI/想法：四角星
            p(); mv(.5, .14); ln(.58, .42); ln(.86, .5); ln(.58, .58); ln(.5, .86); ln(.42, .58); ln(.14, .5); ln(.42, .42); ctx.closePath(); stroke2()
            break
        case "close":  // 关闭 ×
            p(); mv(.26, .26); ln(.74, .74); mv(.74, .26); ln(.26, .74); stroke2()
            break
        case "left":  // ‹
            p(); mv(.6, .22); ln(.32, .5); ln(.6, .78); stroke2()
            break
        case "right":  // ›
            p(); mv(.4, .22); ln(.68, .5); ln(.4, .78); stroke2()
            break
        case "bookmark":  // 书签
            p(); mv(.3, .16); ln(.7, .16); ln(.7, .84); ln(.5, .66); ln(.3, .84); ctx.closePath(); stroke2()
            break
        case "check":  // ✓
            p(); mv(.24, .52); ln(.42, .7); ln(.78, .3); stroke2()
            break
        case "plus":  // ＋
            p(); mv(.5, .24); ln(.5, .76); mv(.24, .5); ln(.76, .5); stroke2()
            break
        case "backup":  // 备份：数据库圆柱
            p(); arc(.5, .26, .24, Math.PI, 0); ln(.74, .74); arc(.5, .74, .24, 0, Math.PI); ln(.26, .26); stroke2()
            p(); mv(.26, .5); arc(.5 * s, .5 * s, .24 * s, Math.PI, 0); stroke2()
            break
        case "pen":  // 笔（局部改写）
            p(); mv(.56, .2); ln(.8, .44); ln(.38, .86); ln(.14, .86); ln(.14, .62); ctx.closePath(); stroke2()
            p(); mv(.62, .26); ln(.74, .38); stroke2()
            break
        case "pause":  // 暂停 ‖
            p(); mv(.38, .26); ln(.38, .74); mv(.62, .26); ln(.62, .74); stroke2()
            break
        case "stop":  // 停止 ■
            p(); rect(.3, .3, .4, .4, .06); stroke2()
            break
        }
    }
}
