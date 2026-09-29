---
name: qianbi-bridge-codes
description: 中文网文桥段类型学受控码表路由（36 码 7 组：爽点/冲突/悬念/情感/过渡/钩子/反例）。为章节细纲选码、按路由词反查码、对账「声明了什么码实际写了什么」。当用户提到桥段设计、爽点套路、打脸/扮猪吃虎/绝境翻盘、细纲选码、桥段对账、套路落点的时候使用。反例码只作审校证据不进路由。
license: MIT
compatibility: 需要 Python 3.8+（仅标准库）；脚本在本 skill 目录 scripts/ 下运行，适用于任何支持 Agent Skills 的客户端。
metadata:
  author: qianbi
  version: 0.22.0
  source: https://github.com/GLFzr/qianbi-novel
---
# 桥段码表：受控词表 + 路由判据

码是**写法契约**不是标签：每码带一句话判据（可指认、可对账）、典型位置（章内
锚点）、典型跨度（章）、路由词与路由场景卡。本版 **36 码 7 组**（爽点 8 码、冲突 5 码、悬念 6 码、情感 6 码、过渡 4 码、钩子 2 码、反例 5 码），
与上游 qianbi-novel 0.22.0 码表逐字一致。

## 流程（三步）

1. **选码**：按本章要写的桥段，在 `references/code-table.md` 或
   `python <skill目录>/scripts/bridge_route.py --list` 里选码；一组选码总数
   要克制（一章通常 1-3 码），每码登记时写明「打算落在哪里」。
2. **写作对齐**：写作时对照码的判据与典型位置——判据对不上段落=未兑现，
   宁可去掉声明也不硬凑。
3. **对账**：成稿后逐码自查「声明的码实际兑现了没有」（上游爽点账本
   beats_declared/beats_delivered 同口径）；可用
   `python bridge_route.py --route <词>…` 反查与本章内容相关的候选码做交叉
   核对。

## 命令速查

```
python scripts/bridge_route.py --list                # 全码清单（按组）
python scripts/bridge_route.py --group 爽点          # 按组过滤
python scripts/bridge_route.py --code DL             # 单码详情
python scripts/bridge_route.py --route 打脸 当众     # 按路由词反查
# 以上均可加 --json
```

## 纪律与边界

- **SJ/SJ2 整码匹配**：SJ（收获兑现）与 SJ2（闭关跳时）前缀撞车，登记与解析
  一律整码 token，不按前缀截断。
- **反例码不路由**：WATER（强行解释）/OOC/BAL（平衡说教）/LOGIC/REP 五码是
  审校证据码（advisory），只在「本章避开了哪些坑」的对账里出现。
- 码表是类型学不是模板清单：同码反复用要换具体事件与物件，判据命中但读感
  重复=失败（上游 deslop 的 formulaic-parallelism 会抓）。
- 完整判据/路由词以 `scripts/_vendor/` 码表源码为唯一真源；金标见 `tests/`。

本包由 qianbi-novel 导出管线自动生成（scripts/build_skills.py），引擎与码表为上游逐字副本；请勿手改产物——上游更新后重跑导出管线并用 --check 对账。
