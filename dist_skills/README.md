# qianbi-skills（自动生成，勿手改）

千笔网文方法论 skill 包：由 qianbi-novel `scripts/build_skills.py` 从仓库当前
成品自动生成——deslop 规则表与引擎逐字 vendoring、桥段码表、状态卡 schema
均以源码为唯一真源。上游版本 **0.20.2**。

- qianbi-bridge-codes（{'codes': 36, 'groups': 7}）, qianbi-deslop（{'rules': 45, 'gold_findings': 5}）, qianbi-state-card（{'byte_budget': 12288, 'columns': 7}）

对账：`python scripts/build_skills.py --check`（与仓库 dist_skills/ 逐字节
比对，有差异 exit 1）。上游：https://github.com/GLFzr/qianbi-novel
