# Wave C 执行卡 v1（C-2 真实走查 · 等用户确认后按此执行）

> 前置（用户 GUI 两分钟）：设置 → 连接与模型 → `or-claude` → ① 粘贴 OpenRouter
> Key → 保存（keyring 脱水）；② 模型选 **`stealth/union-alpha`**；③ 点「测试连接」
> 通过后回一句「开始 Wave C」。
> 预算（R16）：12~18 次调用，仅 `https://openrouter.ai/api/v1 + stealth/union-alpha`；
> 实际花费超预估 2 倍即停；全程对话落盘（WP-27，默认开）；禁 20 章以上长跑。

## 走查序列（执行者驱动 bridge 槽，等价于界面点按；每步留证）

| 步 | 动作（槽/操作） | 验证点 | 顺带复验 |
|---|---|---|---|
| 0 | 读 config：or-claude 有 model+key_ref，否则中止并报告 | R16 围栏自证起点 | — |
| 1 | 测试连接 `testConnection(or-claude)` | 返回成功文案 | **H-8**（空 base_url/非 LLMError 崩溃修复） |
| 2 | 新建走查书 `newProject`（都市/番茄/1 万字） | state.cw.mode=='cw'（B-1 创建时落档） | R17 |
| 3 | 立项确认 `confirmCwStage` | 阶段推进 → cw_core | — |
| 4 | 核心设定：`submitCwMessage` 讨论 → `generateCwDraft` → `confirmCwStage` | 设定/题材定位.md 落盘；对话记录 +≥2 条 | — |
| 5 | 大纲：同 4 | 大纲/大纲.md；parse_outlines 出章号 | — |
| 6 | 世界书与正则：同 4 | 设定/世界书.md + 正则.md | — |
| 7 | 单元细纲：`setCwUnitRange(1,3)` → `generateNextCwOutlines` → `confirmCwStage` | 细纲_第1~3章.md | — |
| 8 | 正文：`generateCwDraft` → 编辑器成稿 → `confirmCwStage` | supervisor 比对 + `confirmChapterLocked` 锁定 | **A-7**（异常转人工不假 PASS） |
| 9 | 导出 `exportProjectOpts("txt",…)` + 报障包 `createBugReport()` | 两产物落盘；包内含对话分片 | A-9 |
| 10 | 证据收集 `collect_walkthrough_evidence.py <书>` | 调用清单 csv / base_url+model 清单 / 汇总 | R16 自证 |

## 停止条件（任一触发即停并报告）

- 累计调用 >18 次（预算 2 倍余量线：单次调用异常重试计入计数）；
- 单次调用报错表明计费异常/模型不可用；
- 走查中发现崩溃（有 A-6 兜底：现场文件 + toast，不再 RC=127）。

## §12 产出映射

| v4 要求 | 产物 |
|---|---|
| 对话落盘账本 | `walkthrough_evidence/调用清单.csv` |
| 调用次数/token | `walkthrough_evidence/汇总.txt` |
| 实付金额 | 汇总（单价由用户/OpenRouter 账单提供后计算） |
| base_url+model 清单 | `walkthrough_evidence/base_url_model_清单.txt`（应仅一行） |

## 已知裁决依赖

- B-2 矩阵两处断点（世界书三件套作业感 / total_chapters）按 v1 文档以提示文案处理；
  若用户裁决要自动迁移 total_chapters，另开一轮。
