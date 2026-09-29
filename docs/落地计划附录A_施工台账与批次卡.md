# Plan A · 施工统一化：统一 DAG + 冲突矩阵 + 批次卡（超级迭代「落地计划」专项）

- 日期：2026-09-29 ｜ 锚点复核：`git log -1` = **HEAD `2de3e9d`（v0.20.1），无漂移**（本文件所有行号均为该 HEAD 实测，核实脚本：`_scratch/superiter/verify_touchpoints.py` / `verify_touchpoints2.py`，.venv 只读运行）
- 输入：`docs/超级迭代蓝图_v1.md`、w4_refactor_plan（B0-B8）、w5_quickwins（30 条）、w3_onboarding（9S+4M+1L）、w5_f123_fix（F1-F3 diff 级）、w5_update（B7→U-A→R3）、w4_model_orch（A-E 五方案）、w4_docs（0.21 前 7 项）、plan_b_engine（10 卡，按任务节点挂入）
- 主仓库只读；本文件为唯一产物。命令一律以仓库根为 cwd、用 `./.venv/Scripts/python.exe` 运行。
- 统一编号规则：**B***=结构债（w4_refactor）；**QW-***=快赢（w5_quickwins，多来源已并入）；**U*/M-CI/M-SCH**=更新链（w5_update）；**卡 N**=引擎落点卡（plan_b_engine，含护栏 G*、原型 P*、机制 T*）；**OB-***=onboarding M/L 批；**DOC-***=文档 M 批；**OA/OB/OC/OD10/OE**=编排五方案；**I18N/H4/PROMO/SKILL/BACKUP**=独立项。同一改动多报告提及的已合并并在「来源」列注明。

---

## 一、任务全量抽取（统一台账：90 行，去重后 76-86 项，视别名归属口径；R1 勘误）

### 1.1 结构债（w4_refactor_plan B0-B8）

| 编号 | 一句话 | 触及文件（已核实） | 人日 | 报告声明依赖 | Wave |
|---|---|---|---|---|---|
| B0 | 基线冻结：dep_graph/static_scan 迁入仓库 scripts/，记录 1132+ 全绿与结构基线（bridge 6249 行/42 违规边/3 SCC/9 死函数/microcycle 862 行） | `scripts/dep_graph.py`、`scripts/static_scan.py`（新，源在 `_scratch/superiter/scripts/`，已确认存在） | 0.5 | 无 | 0 |
| B1 | 死函数清理：9 个中删 8 个（`summarize_findings` 因卡6S「复活」**豁免**——w5_quickwins F3 裁决）+ conftest 证据登记 fixture + CONTRIBUTING 一行规约 | `app/deslop.py:378`(豁免)、`app/core/co_dialogue.py:60`、`app/core/shared_prefix.py:112`、`app/core/versions.py:161`、`app/core/volume_session.py:592`、`app/presets/__init__.py:492`、`app/prompts/skill_rules.py:135,141`、`app/ui/demo_replay.py:109`、`tests/unit/conftest.py`、`tests/unit/test_receipt_guards.py:33` | 0.25 | B0 | 0 |
| B2a | 槽位常量下沉：新建零依赖 `app/slots.py`，config re-export，5 消费方改 import，消 config×5 边 | `app/slots.py`(新)、`app/config.py`、`app/core/agent_tools.py:181`、`app/core/canon_audit.py`、`app/core/co_dialogue.py`、`app/core/gates.py:82-83`、`app/core/stages.py` | 0.5 | B0 | 0 |
| B2b | 拆环1 project↔wb：`worldbook_text/worldbook_anchors`（project.py:424-448 实测）迁入 wb.py，wb 三处延迟 import 升模块级 | `app/project.py:16,424-448`、`app/wb.py:480,691,728` + core 5 消费方 | 0.5 | B0；建议先于 B5 | 0(可选)/2 |
| B2c | 拆环2 skill_rules↔writing：提取共享 `app/prompts/deslop_rules.py`（skill_rules.py:81 与 writing.py:258 实测互引） | `app/prompts/deslop_rules.py`(新)、`app/prompts/skill_rules.py:81`、`app/prompts/writing.py:258` | 0.25 | B0 | 0 |
| B2d | 拆环3 history_compaction↔volume_session：`han_tokens` 下沉 `app/core/text_metrics.py`（主路径环，风险最高先拆） | `app/core/text_metrics.py`(新)、`app/core/history_compaction.py:307,608`、`app/core/volume_session.py:106` | 0.5 | B0；与卡9-P2/C3 同邻域语义审查串行 | 0 |
| B4 | Orchestrator.run 测试网：`test_orch_run_smoke.py`（5 条路径）+ `test_microcycle_steps.py`（7 步 pin=行为快照） | 仅新增 2 个测试文件 | 2 | B0；★B3 前置 | 0 |
| B3 | chapter_microcycle 切七阶段：`_MicroCycle` dataclass（18 共享变量）+ `_mc_assemble…_mc_finalize`，签名不变；**禁止一次全搬** | `app/core/stages.py:1547-2408`（实测 def=1547 ✓） | 3.5 | **B4**（pin 先在未拆函数生效） | 0 |
| B5a | project.py/wb.py 搬 core（旧路径 shim 显式名单），消 14 边 | `app/project.py`、`app/wb.py` → `app/core/`、+2 shim、`scripts/dep_graph.py` 分层表 | 1.5 | B2b | 2(插队) |
| B5b | deslop.py/mustscan.py 搬 core，消 5 边；**卡6S/卡7 先落后搬，整体平移** | `app/deslop.py`、`app/mustscan.py` → `app/core/`、+2 shim | 1 | B2b；与卡6S 协调 | 2(插队) |
| B5c | usage/dialogue_log/diagnostics 搬 core；dep_graph 增 base 层（secrets/logger/slots）；完成后仅剩 13 条良性边 | `app/usage.py`、`app/dialogue_log.py`、`app/diagnostics.py` → `app/core/`、+3 shim、分层表 | 1.5 | B2a（slots 在 base） | 2(插队) |
| B6 | 共写桥面测试：CoWriting 状态机迁移表全覆盖 + bridge 槽级单测；宿主文件与卡1 合并施工（见批次 C08） | 新增 `tests/unit/test_cw_state_machine.py`、`tests/unit/test_cw_bridge_slots.py` | 2 | B0 | 0(并入卡1批)/2(余量) |
| B7 | update 链路补测：download/resume/哈希失败 + **U-1 损坏半截文件毒化续传钉子** + 状态机离屏分支 | 新增 `tests/unit/test_update_install_flow.py`（源锚：`app/update_install.py:42-102,126-135,138-144`、`app/ui/bridge.py:2095-2141`） | 1 | B0；★一切 update 功能动刀前置 | 0 |
| B8a | bridge worker/model 层 12 类+10 纯函数平移 workers.py（≈894 行，零 QML 面） | `app/ui/bridge.py:33-926` → `app/ui/workers.py`(新) | 0.5 | B0 | 2(插队) |
| B8b | Updates 域 17 方法 → UpdatesMixin（Signal 留主类）；**U-A/U-B/R3 全部落地后整体平移** | `app/ui/bridge.py` → `app/ui/bridge_updates.py`(新) | 1 | B0；B7→U-A→U-B→R3 之后 | 2(插队) |
| B8c | Io 域 20 方法 → bridge_io.py | 同上 → `app/ui/bridge_io.py`(新) | 1 | B0 | 2(插队) |
| B8d | Settings/Connections 域 20 方法 → bridge_settings.py，顺带消 ui→llm 4 违规边中 provider/router 直连 | 同上 → `app/ui/bridge_settings.py`(新) | 1.5 | B0；OA 落地后做免二次搬 | 2(插队) |
| B8e | 共写族 ≈600 行 → CwMixin；**卡1+卡10 之后搬**；新 Signal/Property 已按 mixin 策略在主类声明区 | `app/ui/bridge.py` 共写族 → `app/ui/bridge_cw.py`(新) | 2 | B0；卡1、卡10 之后 | 2(插队) |

### 1.2 快赢 30 条（w5_quickwins，含多来源合并）

| 编号 | 一句话 | 触及文件（已核实） | 人日 | 依赖 | Wave |
|---|---|---|---|---|---|
| QW-A1 | 新建书 toast 按档位指路（共写档不再说「点开始」）＝w3-S1 | `app/ui/bridge.py:1292-1294`（newProject，B8 保留层） | 0.25 | B0 | 0 |
| QW-A2 | 共写档「开始」按钮换「去共写·{阶段}」CTA + demo 脚本同步＝w3-S2 | `app/ui/qml/PipelinePanel.qml:378-385`(实测 379)、`app/ui/bridge.py`(新增 startCta/gotoCwStage)、`assets/demo/script.json:56-58` | 0.5 | B0；全仓 grep `startButton` 联动 | 0 |
| QW-A3 | startPipeline missing[] 补空模型检查＝w3-S3 | `app/ui/bridge.py:1395-1407` | 0.25 | B0 | 0 |
| QW-A4 | test_connection 空模型黄牌＝w3-S4 | `app/llm/client.py:787-817` | 0.25 | B0 | 0 |
| QW-A5 | `_slot_readiness()` 帮手 + 共写 LLM 调用前拦截＝w3-S5（软开局 M1 复用同一函数） | `app/ui/bridge.py`（共写族，符号锚） | 0.25 | B0；先于 OB-M1 | 0 |
| QW-A6 | 细纲范围预填 1~10 + ±10 即时校验＝w3-S6 | `app/ui/qml/components/CwDialogueDock.qml:348,384`(unitStartBox)、`app/ui/bridge.py:4361`(setCwUnitRange) | 0.25 | QW-A5（共享文案表） | 0 |
| QW-A7 | 共写进 prose 阶段自动打开第 1 个未锁章＝w3-S7 | `app/ui/bridge.py:4116-4118,4319-4321` + 阶段切换钩子（**报告锚 `_on_cw_stage` 不存在，见缺口 G1**） | 0.25 | QW-A5 | 0 |
| QW-A8 | 六阶段「确定」后固定「下一步」预告 toast（5 张文案表）＝w3-S8 | `app/ui/bridge.py:5123`(_on_cw_sum_done) advance 分支 | 0.25 | QW-A5 | 0 |
| QW-A9 | 首启向导 checklist 化 + 更新检查状态行＝w3-S9 | `app/ui/qml/components/WizardDialog.qml`(137 行) | 0.25 | B0 | 0 |
| QW-A10=卡1 | 共写 supervisor 链三伤 F1-F3（删覆盖版复活 C2 逃生门/派单走 compose/结论门+留痕分口径）＝w5_f123_fix 成品 diff | `app/ui/bridge.py:4756/4845/972/1089/4859/4790/4895/4937`、`app/core/co_dialogue.py:453`(def，卡1 引 465-478 为体内行)、`app/ui/qml/components/CwDialogueDock.qml:150-170`、`tests/unit/test_cw_prose_check.py:148`(桩扩参)、新增 `tests/unit/test_cw_bridge_slots.py` | 1.5-2 | B0；**B8e 必须在其后** | 0 |
| QW-A11 | w1_ux 小修四件（tooltip 虚标/Console 话术错位/read_chapter 误吃当前章/「去一下AI味」漏「一下」） | `app/core/agent_tools.py`、`app/ui/bridge.py:4155`(_ui_tool_dispatch)、`tests/probe_parse_instr.py`(scratch 回归) | 0.5-1 | B0 | 0 |
| QW-B1 | LLM 容错四件套：`<think>` 流式过滤/finish_reason 人话/429 读 Retry-After/非流式地板 2048，**顺手带 E 识别层 last_finish_reason**＝w4_model_orch D6-D9+E① | `app/llm/client.py:606-785`(_stream_messages)、`:242-259`(_retry_wait)、`:514-541`、`:844-854`(clean_llm_output) | 1-1.5 | B0 | 0 |
| QW-B2 | H-7 残项：降级 toast 报被剥参数名 + 按名即剥加值校验白名单 | `app/ui/bridge.py`(设置域,符号锚) + `app/llm/client.py:313` | 0.5 | B0 | 0 |
| QW-B3=B7 | （同 B7，不重复计） | — | — | — | — |
| QW-B4=U-C | 旧安装包保留策略（当前+上一版）：见更新链 UC | `app/update_install.py` | 0.5 | 无（弱依赖 U-A） | 0 |
| QW-B5=M-CI | `check_manifest_consistency.py` 三通道一致校验 + GH Actions release-consistency job | `scripts/check_manifest_consistency.py`(新)、`.github/workflows/*`、`docs/release_checklist.md` | 0.5-1 | 无 | 0 |
| QW-B6=M-SCH | latest.json stats 构建时回填 + notes 去内嵌数字 | `scripts/build_release.py`（真实路径，:404-434 区插两行）、`latest.json` | 0.5 | 无 | 0 |
| QW-B7 | H-11 残项：quote_verified 隐式契约跨模块护栏钉（写 stages.py:3128 / 读 bridge.py:279，双双实测吻合） | 测试面新增断言 | 0.25 | B0 | 0 |
| QW-B8 | H-18：README.en.md:354「三槽出厂 V4 Pro」段重写（并入 QW-D4 执行） | `README.en.md:354` | 0.25 | B0 | 0 |
| QW-C1=卡6S | deslop 度量层从零到一：`deslop_metrics.py` + **复活** summarize_findings + trailer 收窄 600 字窗 + Δ 报告 + to_record 扩 metrics | 新增 `app/deslop_metrics.py`；`app/deslop.py:378,40-53`、`app/core/gates.py:38-46`、`app/core/stages.py:1956,2013,2034`(消费)、`app/core/co_dialogue.py:619,639`(before/after 升级) | 1.5 | B0；**B1 豁免 summarize_findings**；deslop.py 在 B5b 清单：先落后搬 | 1 |
| QW-C2=卡9-P4 | 55% 断流闸 check_collapse + 整段复读 blocking + 敏感词 advisory | `app/core/gates.py`(新函数)、`app/deslop.py` 旁、`assets/sensitive_words.txt`(新) | 0.5-1 | B0 | 1 |
| QW-C3=卡9-P2 | P2 状态卡生成器 build_state_card（12KB 七栏） | `app/core/memory.py`(或新 state_card.py) + `app/core/co_dialogue.py:156`(compose_reference_block 消费) | 1 | B0；与 B2d 同邻域语义审查串行 | 1 |
| QW-D1 | hero 图去重（hero_cw.png 与 shot_co_writing.png 字节级相同，实测 IDENTICAL 339,326B） | `docs/hero_cw.png`、`README.md:20,46` | 0.25 | 无 | 0 |
| QW-D2 | 数字校正三连：README 1061→实collect、探针 50、latest.json 版本行 0.20.1+stats | `README.md:383`、`latest.json`(实测仍 0.20.0/49 支/1122) | 0.25 | **QW-D3 先装报警器** | 0 |
| QW-D3 | `scripts/check_docs.py` 口径报警器（五项检查）+ 接入 tests.yml + build_release 第 7 闸 | `scripts/check_docs.py`(新)、`scripts/build_release.py`、`.github/workflows/tests.yml` | 0.5 | 无 | 0 |
| QW-D4 | EN README 同步：数字(594→1132/44→50) + H-18 V4 Pro 段 + 顶部滞后声明 | `README.en.md:354,378,384,451`(全实测) | 0.5 | B0 | 0 |
| QW-D5 | `docs/README.md` 索引页（三类读者导航） | `docs/README.md`(新) | 0.25 | 无 | 0 |
| QW-D6 | 排障页 `docs/排障_v1.md`：13 条真实报错对照（文案逐字抄自 client.py:461,551,795-815 等）+ 日志/dump/报障包三件套 | `docs/排障_v1.md`(新)；与 QW-D3 检查5 联动 | 1 | 无 | 0 |
| QW-D7 | CHANGELOG.md:1229 死锚 `README.md#使用指南` 顺手改 | `CHANGELOG.md:1229`(实测) | 0.1 | 无 | 0 |
| QW-D8 | README 徽章补 2 枚（Discussions+Release 下载） | `README.md` | 0.25 | 无 | 0 |
| QW-D9 | 版权夹具清理：斗破专名/《守夜人》真实作者名改虚构 | `tests/` 夹具改名 | 0.25 | 无 | 0 |
| QW-E1=卡8-G1 | G1 字数预算断路器（首稿超 N×不进 trim/deslop/审校）+ trim 最低压缩量守卫 | `app/core/stages.py:1814-1819`(插点实测)、`:1907-1930`(trim 环/守卫/trim_over) | 0.5-1 | **B3**（挂点在函数体内；B3 前顺延，或作为 `_mc_word_gate` 首个语义 PR）；假客户端单测自保 | 1 |
| QW-E2=卡8-G3 | G3 跨章待修断路器（连续 K 章 needs_fix→auto_pause） | `app/core/orchestrator.py:486-496`(章循环收尾实测)、`:135-139`(auto_pause)、`app/core/stages.py:2177-2186`(need_human 升 error) | 0.5 | 软依赖 B4（假 client 单测自保） | 1 |
| QW-E3=卡2 | T3 伏笔到期引擎·确定性部分（parse_recovery_window/urgency 排序/超期前缀/批次 L0） | `app/core/tracking_store.py:22,182,211,234`(实测±1)、`app/core/memory.py:73`、`app/core/l0_checks.py:106`、`app/core/stages.py:1101,3676,2433+`(消费点实测) | 0.5-1(S 档)/1.5-2(完整卡) | **B4 后即可，不被 B3 阻塞**；与 C3 串行 | 1 |

### 1.3 更新链（w5_update；判据 A 主体）

| 编号 | 一句话 | 触及文件（已核实） | 人日 | 依赖 | Wave |
|---|---|---|---|---|---|
| U-A | 静默安装编排：installer.iss [Run] 去 skipifsilent(:66 实测) + [Code] 写 `.update_done` marker；installUpdateNow 加 flush_draft+journal+shutdown()+`/SILENT /NORESTART /LOG`；首启 journal×marker 对账 | `tools/installer.iss`、`app/ui/bridge.py:2095-2141`、`app/main.py:137`(对账挂点，实测)、`app/config.py`(journal 路径) | 2-3 | **B7 之后、B8b 之前（顺序钉死）** | 2 |
| U-B | 一键「下载并自动安装」+ 5s 倒计时可取消 + 两步确认改单步（probe_update_ui.py:289-292 断言随改） | `app/ui/bridge.py`、`app/ui/qml/components/UpdateDialog.qml`、`tests/probe_update_ui.py` | 0.5 | U-A | 2 |
| U-C=QW-B4 | 旧安装包保留（当前+上一版，更早删除） | `app/update_install.py`(+清理函数) | 0.5 | U-A 后正式接线，可先行落函数 | 0 |
| R3 | 引导回滚：journal first_run 相位 + 更新后首启崩溃检测（dump mtime）+ 恢复对话框 | `app/update_rollback.py`(新)、`app/ui/bridge.py`(接线)、`app/ui/qml/Main.qml`(横幅) | 1.5-2 | U-A；可与 B8b 并行（新模块） | 2 |
| M-CI=QW-B5 | （同上） | | | | 0 |
| M-SCH=QW-B6 | （同上） | | | | 0 |
| UDOC | README:91/96 口径（「全程不用离开应用」在静默版落地后才成立）+ 手册「更新与回滚」节 + 排障页更新条目 | `README.md:91,96`(实测)、`docs/排障_v1.md` | 0.5 | U-A/R3 后收尾 | 2 |

### 1.4 引擎机制（plan_b_engine 10 卡；卡1/卡2/卡6S/卡8-G1/G3/卡9-P2/P4 已在上表，此处列余量）

| 编号 | 一句话 | 触及文件（已核实） | 人日 | 依赖 | Wave |
|---|---|---|---|---|---|
| 卡3=T1 | 爽点节奏带账本：sidecar `追踪/爽点账本.json` + rhythm_findings 三规则 + 双通道回写 + cw 细纲字段扩展 | `app/core/satisfaction.py`(87 行，实测)、`app/core/l0_checks.py:106,195`、`app/core/stages.py:1203,1313,1758-1761`(注入实测)、`:2235-2248`(finalize 写点实测)、`app/prompts/co_writing.py:259-293`、`app/ui/bridge.py:4460`(_on_cw_batch_done)、新 `tests/unit/test_satisfaction_ledger.py` | 4-5 | **B3 硬前置**（finalize 写点在 862 行函数体内）；cw 字段依赖卡1；⚠ 接线护栏 `test_satisfaction_engine.py:191-199` 钉死「正文 3 处+细纲 2 处」，加注入点须同步改钉值 | 3 |
| 卡4=T2 | 钩子追读链账本：7 钩型受控词表 + 细纲字段升级 + F 维回写 + supervisor 对账域 | 新增 `app/prompts/hook_vocab.py`、`app/prompts/planning.py:202,206,239`(实测)、`app/prompts/review.py:169-175`(F 维实测)、`app/prompts/co_writing.py:353-397`、`app/core/l0_checks.py`(hook_findings)、`app/core/co_dialogue.py:391`(SupervisorWorker)、新 `tests/unit/test_hook_ledger.py` | 3.5-4.5 | **卡1 硬前置**（supervisor 链不修就是第四剧场）；⚠ W0c 钉测 `test_cw_prose_check.py:95-101` 两档共用 | 3 |
| 卡5=T5 | 桥段码账本（36 码表+4 打法卡+码优先路由）；版权绿档 | 新增 `app/prompts/bridge_codes.py`、`app/prompts/bridge_cards.py`、`app/prompts/planning.py`、`app/prompts/scene_cards.py:189,277`(路由实测)、`app/core/stages.py:1754`(craft_block 实测)、`app/core/l0_checks.py` | 4-6 | 卡3 同批（共享账本基建）；**版权裁决②关联** | 4 |
| 卡6M | deslop 规则 28→≥45 + maskQuoted 重写 `_in_dialogue`(:118) + 书级白名单 + review 二轴 | `app/deslop.py`、`app/prompts/writing.py:214-240`(lieflat 切片同步纪律)、`app/core/shared_prefix.py`(D9 复用) | 3-4 | 卡6S 先行；B5b 后搬 | 3(可拆Wave2) |
| 卡7 | must 机器复扫闭环：改写采纳前双复扫 + G7 回退对账 + findings_to_prompt_text 带规则 ID + 3-gram 防复用 | `app/core/stages.py:2009-2013,2024-2040`(采纳点/G7 实测)、`:958-968`(pinned 护栏参照)、`app/deslop.py:390-398`、`app/mustscan.py:68-79` | 1-1.5 | 卡6S 弱依赖（metrics 出口）；无 B3 依赖（B3 后落在 _mc_deslop） | 2 |
| 卡8-G2=OE | 截断稿拦截：prose/trim/deslop 相位 length 稿按 G1 处理（识别层已随 QW-B1 落地） | `app/core/stages.py`(消费 last_finish_reason)、`app/llm/client.py`(识别层已备) | 1 | QW-B1 + 卡8-G1 | 2 |
| 卡8-G4 | 相位看门狗：第 N 章落库 ⇒ 摘要产物存在，缺→error，连续 2 章→auto_pause | `app/core/orchestrator.py:488-496` | 1.5 | B4 | 3 |
| 卡8-G5 | usage 台账准实时告警（顶格/单章成本/无 tracking 行）→ `state.anomalies` 新键 | `app/usage.py:157-194`(record 实测)、`app/core/state.py:366`(validate_state 键型表)、`app/core/volume_session.py:84`(record_event) | 2 | B4 | 3 |
| 卡8-G6 | 记账不可中断区：落库后 in_epilogue，stop 推迟章界（治 T3-1 30 章停摆） | `app/core/stages.py:2233-2248`(write_file:2233/checkpoint:2236,2248 实测)、`app/core/orchestrator.py`(pending_stop) | 1-1.5 | B4 | 3 |
| 卡8-G7 | 检测口径与短章地板：word_count_precheck 加上限报告 + 短章禁静默定稿 + 阻断数千字归一 | `app/core/gates.py:131-160`(实测) | 1 | B4 | 3 |
| 卡9-P1 | P1 引文锚定 → `app/core/fact_ledger.py`（extract/normalize/两级锚定/逐条拒收）+ `追踪/事实账本.jsonl` | 新增 `app/core/fact_ledger.py`；`app/core/stages.py:2238`(finalize)、`app/core/co_dialogue.py:700-790`(MemoryBackflowWorker/_run_backflow:744 实测)；原型 `_scratch/superiter/proto/p1_quote_anchor.py` | 2.5-3 | **卡10-CW-G6 前置**（锁定⇒账本行对账）；卡2 长期地基 | 3末/4 |
| 卡9-P3 | P3 四查 → `app/core/maintenance.py`（待确认卡片形态，不进 cw["report"] 单槽） | 新增 `app/core/maintenance.py`；`app/ui/bridge.py:4565`(_do_lock_chapter)、`app/core/state.py:403` 旁、`app/core/co_dialogue.py:156` | 2.5-3 | 卡9-P1（伏笔 evidence） | 3末/4 |
| 卡10 | CW-G4~G7 余四条护栏（上限入账/取消代际化+半提交对账/反哺看门狗/打回确认） | `app/ui/bridge.py:4402,4259,1312,5227`、`app/core/co_dialogue.py:483,529-537`(OutlineBatchWorker 半提交实测)、`app/core/co_writing.py:20-221` | 3.5-4.5 | B0；卡1（G1-G3 同链先修）；**CW-G6→卡9-P1** | 2 |

### 1.5 onboarding M/L 批（w3_onboarding）与文档 M 批（w4_docs）

| 编号 | 一句话 | 触及文件 | 人日 | 依赖 | Wave |
|---|---|---|---|---|---|
| OB-M1 | 软开局全量（示例卡片/子态/三退出/交还卡片） | `app/core/co_writing.py`、`app/ui/qml/components/CwDialogueDock.qml`、`app/ui/bridge.py` | 2-3 | **QW-A5/QW-A1（轨道先行）** | 3 |
| OB-M2 | 向导内嵌迷你连接表单 | `WizardDialog.qml` + SettingsPanel 组件抽取 | 1.5 | OB-M3 验收后 | 3 |
| OB-M3 | 书架就绪横幅（Key/模型/首书 checklist） | `app/ui/qml/BookshelfPanel.qml`(实际路径在 qml/ 根，非 components/) + `connReadySummary()` | 1-1.5 | QW-A5 | 3 |
| OB-M4 | 静态示例书《种子书》零 Key 只读入口 | `app/ui/demo_pack.py`(127 行，实测)、`BookshelfPanel.qml`、演示守卫复用 | 1-1.5 | 无 | 3 |
| OB-L1 | demo 脚本扩六阶段全链伪跑 | `app/ui/demo_director.py`、`assets/demo/script.json`、replay 资产 | 5 | 多数 UI 改动落定后 | 3(缓) |
| DOC-4 | README 首屏重构（痛点宣言+数字证据条+3 步开写+skill 对比列，13 节骨架） | `README.md`、`README.en.md` | 2 | QW-D1/D2/D3 先行 | 3 |
| DOC-8 | README 证据链区块（产出物三样例+usage 三行） | `README.md` | 1.5 | DOC-4 | 3 |
| DOC-9 | 手册 v2 ≥500 行 + 面板覆盖核对 | `docs/用户手册_v2.md`(新)、`scripts/check_docs.py` 检查2/4 | 2.5 | QW-D6 | 3 |
| DOC-10 | 内嵌帮助：随包 HTML + F1 + About 入口 | `scripts/build_release.py`、`app/ui/qml/components/AboutDialog.qml`、`app/selftest.py` 断言 | 1.5 | DOC-9 | 3 |

### 1.6 编排五方案（w4_model_orch）与独立项

| 编号 | 一句话 | 触及文件 | 人日 | 依赖 | Wave |
|---|---|---|---|---|---|
| OA | A 方案·阶段级模型路由 UI（四阶段组下拉，存预设 stage_params，零新配置键） | `app/ui/bridge.py`(设置新节，**独立 controller 不摊大文件**)、`app/model_strategy.py:20-29`(+2 卡)、`app/presets/__init__.py:221-359`(零改动) | 1 | 无结构债前置；先于 B8d 免二次搬 | 2 |
| OB-cost | B 方案·成本面板（今日/本书/月三层+章列成本标注+偏差告警展示面） | `app/usage.py`(book-scope 聚合)、`app/ui/bridge.py`(独立 controller)、`app/core/state.py:575`(append_history 行) | 2-3 | **卡8-G5 先行**（共享阈值引擎） | 3 |
| OC | C 方案·批量挂机（BatchRun：N 章排队/三层熔断/预算上限/挂机面板） | 新增 `app/core/batch_run.py`、`app/core/orchestrator.py`、`app/ui/bridge.py`、`app/core/offpeak.py`(复用) | 6-8 | **卡8-G6+卡8-G3 硬前置**；G1/G5 强烈同批；`tests/long_run.py` 转正收编 | 3 |
| OD10 | D 方案第 10 项·Ollama/LM Studio 连接体检一键化 | `app/llm/client.py`(/api/tags 双探测)、`app/llm/providers.py` | 1-2 | 无 | 2 |
| I18N | i18n 单语声明 A 路（蓝图裁决④已定，触点待补——见缺口 G12） | `README.md`(声明行) | 0.5-1 | QW-D3（纳入检查项更稳） | 0 |
| H4 | H-4 主体：跨线程 load→改→save 丢更新修复（蓝图钉死 Wave 3 首项，与 OC 同批） | 待施工设计（见缺口 G2） | 2-3 | B4；先于 OC | 3 |
| PROMO | 促销片防腐 pass（硬编码数字清除） | 待触点清单（见缺口 G6） | 0.5 | QW-D2 | 1 |
| SKILL-S/ML | skill 包三件：金标夹具冒烟 0.5 + 发布仓样例 0.5 + 发版联动 0.5；M/L 件另 3 | 待读 w3_skill_export.md 核触点（见缺口 G5） | 1.5+3 | 无 | 2 |
| BACKUP | 自动备份（关项目/关应用 zip） | core 新模块 + `app/ui/bridge.py:2169,5389`(shutdown/_maybe_auto_backup 雏形实测) | 1-1.5 | 无（见缺口 G4） | 2 |

---

## 二、触点矩阵（文件 × 任务）与漂移标注

### 2.1 漂移结论总表（逐文件实测 vs 报告引用）

| 文件（真实路径） | 状态 | 漂移判定 |
|---|---|---|
| `app/ui/bridge.py`（6249 行） | 存在 | **46 个行锚全部吻合（±0~3 行）**：class Bridge=930、Signal 区 968-976(supervisorFailedChanged=972)、旗标区 1089、newProject=1254(toast 1292-1294)、startPipeline=1382(拦 1392-1394/missing 1395-1407)、checkForUpdates=1896、installUpdateNow=2095、shutdown=2169、saveConnection=2765、setSlot=2815、submitCwMessage=4015、generateCwDraft=4098(拦 4116-4118)、confirmCwStage=4298(prose 拦 4319-4321/痕检 4330-4335)、setCwUnitRange=4361、_start_cw_outline_validation=4402、_on_cw_batch_done=4460、confirmChapterLocked=4483、_do_lock_chapter=4565、F1 死版=4756、_on_cw_supervisor_error=4776、retrySupervisor=4784、forceLockChapter=4790、**双定义=4756+4845**、_on_cw_supervisor_done=4859、_dispatch_cw_rewrite=4895、dispatchCwReport=4937、_on_cw_sum_done=5123、_rollback_to=5227、_maybe_auto_backup=5389 |
| `app/core/stages.py`（3727 行） | 存在 | **全部区段锚吻合**：chapter_microcycle def=1547、stage_chapter_outlines=1101、_generate_outline_batch=1159、满意注入 1203/1313、craft_block 调用=1754、_beat_block=1758-1761、字数闸 1814-1819、trim 环 1907-1930、need_human 2177-2186、write_file(chapter_path)=2233、追踪区 2235-2248、deslop 采纳 2009-2013、G7 2024-2040、pinned 护栏 963-966、review_l0_block=2413、upsert 调用=3676、quote_verified=3128、record_event 先例 1468/1938 |
| `app/llm/client.py`（854 行） | 存在（**真实路径 app/llm/client.py**，报告常写裸 `client.py`） | test_connection=787、_stream_messages=606、_retry_wait=242、clean_llm_output=844、finish_reason=518-532、空流自愈=421、未选模型文案=461,614；`last_finish_reason`/`<think>`/`Retry-After` **均不存在**（=QW-B1 施工对象确认） |
| `app/core/co_dialogue.py`（790 行） | 存在 | parse_supervisor_report **def=453**（卡1 引 465-478 是函数体内行，漂移 12 行→函数名锚）；SupervisorWorker=391、OutlineBatchWorker=483（半提交 531-537）、MemoryBackflowWorker=700、_run_backflow=744、compose_reference_block=156、cap_discuss_reply=83、clear_transcript=60、before_counts=619,639、apply_foreshadow_diff 调用=771；`supervisor_report_has_conclusion` 不存在（=卡1 新增确认） |
| `app/core/gates.py`（160 行） | 存在（真实路径 app/core/gates.py） | to_record=38、scan_deslop=67、GATE_MARK_CONTINUE/STRICT=82/83、word_count_precheck=131 |
| `app/deslop.py`（398 行）/`app/mustscan.py`(116)/`app/usage.py`(238)/`app/project.py`(715)/`app/wb.py`(744)/`app/diagnostics.py`(48)/`app/dialogue_log.py`(157) | 存在于 app/ 顶层 | summarize_findings=378、violation_keys=68、set_chapter=145/record=157、from . import wb=16、worldbook_text/anchors=424/435、wb 三处延迟 import=480/691/728、dump_failure=14 —— 与 w4_refactor 全部吻合（B5 搬迁对象确认仍在顶层） |
| `app/core/orchestrator.py`（536 行） | 存在 | run=339、microcycle 调用=483、auto_pause=135-139、append_history=491、G9=493+、_dump_failure=531 |
| `app/core/tracking_store.py`（242 行） | 存在 | _FORESHADOW_COLS=22（卡2 引 21，±1）、load_foreshadow=182、apply_foreshadow_upserts=211、render_foreshadow_md=234；「已失效」不存在（=卡2 新增确认） |
| `app/core/memory.py`（669 行）/`app/core/satisfaction.py`(87)/`app/core/l0_checks.py`(229) | 存在 | unfished_foreshadows=73、apply_foreshadow_diff=423（卡2 引 427，±4）；_BEAT_LINE_RE=23、beat_declared=61、prose_beat_block=78；beat_findings=106、build_v5_block=195 |
| `app/prompts/planning.py`(344)/`review.py`/`co_writing.py`(397)/`scene_cards.py`(292)/`skill_rules.py`(256)/`writing.py`(343) | 存在 | 章节定位=202、章首钩子=206、章尾钩子=239；F 维=169-175、F_HOOK 标记=194；CO_UNIT_OUTLINE_PROMPT=259、CO_SUPERVISOR_PROMPT=353、DISCUSS_MODE_BLOCK=104；SCENE_CARDS=10、chapter_to_cards=189、craft_block=277；skill_rules.py:81 调 writing（**def builtin_deslop_static_rules 在 writing.py:221**，w4 引 :81 是调用点非定义）；writing.py:258-260 反向引 skill_rules ✓ |
| `app/core/history_compaction.py`(616)/`volume_session.py`(969) | 存在 | resolve_volume 延迟 import=305-308（w4 引 307 ✓）、opening_marker=608 ✓；han_tokens 反向 try/except import=106 ✓、new_volume_session=592、record_event=84 |
| `app/update_check.py`(578)/`app/update_install.py`(144) | 存在 | check=430、verify_manifest=311、CHANNEL_LABELS=58、**is_new 即 save_cache=462-463（U-2 确认）**；download=42、resume 哈希=53-63（U-1 确认）、disk_space_ok=126、stale_partial=138 |
| `app/main.py` | 存在（**真实路径 app/main.py**；w5_update 写裸 `main.py:137`） | aboutToQuit.connect(bridge.shutdown)=137 ✓ |
| `scripts/build_release.py` | 存在（**真实路径 scripts/build_release.py**；报告写裸 `build_release.py`） | 行号未逐一复核→施工用符号锚（质量闸门区/latest.json 回填区） |
| `tools/installer.iss`(138 行) | 存在 | **skipifsilent=66 ✓**、InstallDelete=45、CloseApplications=31 |
| `app/ui/qml/PipelinePanel.qml`(835) | 存在 | **startButton=379 ✓**（w3 引 378-385） |
| `app/ui/qml/components/CwDialogueDock.qml`(716) | 存在 | supervisorFailed=153,164 ✓、retrySupervisor=156、forceLockChapter=167、unitStartBox=348,384 |
| `app/ui/qml/BookshelfPanel.qml` | 存在（**在 qml/ 根，非 components/**；OB-M3/M4 触点注意） | — |
| `app/ui/qml` 全树 | **42 个 .qml 实测确认**（w4_docs 口径一致） | — |
| `tests/unit/conftest.py`(40)/`test_receipt_guards.py`(489) | 存在 | QIANBI_CONFIG_DIR 隔离+Keyring 围栏 ✓（W1「缺 conftest」口径已被 w4 修正，实测确证）；EVIDENCE_CALLEES=33 |
| `tests/unit/test_cw_prose_check.py`(182) | 存在 | **桩 `_spawn_cw_dialogue` 无 mode 形参=148（F2 逃测原因实证）**；W0c 钉测在 :95-101 区 |
| `tests/unit/test_satisfaction_engine.py`(199) | 存在 | **接线护栏 191-199：`+ _beat_block +` ×3 + `_satisfaction_outline_directive(ctx.cfg)` ×2 钉死**（卡3/卡4/卡5 改注入点必须显式改钉） |
| `tests/probe_update_ui.py`(428) | 存在 | 「两步确认」断言=289-292 ✓（U-B 改写对象）；startDetached 尚无断言（U-A 新增） |
| `assets/demo/script.json` | 存在 | pipeline_intro=56、target startButton=58（QW-A2 联动点） |
| 文档漂移现场 | 全部实证 | `README.md:383`=1061；`README.en.md:354`=V4 Pro、:378/:451=594、:384=44 probe；`latest.json`=0.20.0+49 支+1122（代码 0.20.1/实测 50 探针）；`CHANGELOG.md:1229`=死锚；hero_cw.png≡shot_co_writing.png（SHA256 同，339,326B）；`docs/README.md`、`docs/排障_v1.md`、`scripts/check_docs.py`、`scripts/dep_graph.py`（仓库侧）、`app/slots.py`、`app/core/text_metrics.py`、`app/prompts/deslop_rules.py`、`app/deslop_metrics.py`、`app/core/fact_ledger.py`、`app/core/maintenance.py`、`app/update_rollback.py`、`app/prompts/hook_vocab.py`、`app/prompts/bridge_codes.py`、`tests/unit/test_cw_bridge_slots.py`、`test_cw_state_machine.py`、`test_orch_run_smoke.py`、`test_microcycle_steps.py`、`test_update_install_flow.py` 均**不存在（=新建确认）** |
| `app/ui/bridge.py` `_on_cw_stage` | **不存在** | w3_onboarding QW-A7 的钩子名为虚构锚（见缺口 G1） |

### 2.2 文件 × 任务触点矩阵（仅列 ≥2 任务热点；√=触及）

| 文件 | B0 | B1 | B2a | B2b/c/d | B3 | B4 | B5a-c | B6 | B7 | B8a-e | 卡1 | 卡2 | 卡3 | 卡4 | 卡5 | 卡6S/M | 卡7 | 卡8 G1-G7 | 卡9 P1-P4 | 卡10 | QW-A 组 | QW-B1/B2 | QW-C 组 | U 线 | OA/OB/OC | OB-M | DOC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| app/ui/bridge.py | | | | | | | | √ | √ | √√√ | √ | | | √(回写) | √(对账) | | | √(G3 接线) | √(P1/P3 挂) | √ | √(A1-A8,A11) | √(B2) | | √(UA/UB/R3) | √(OA/OB/OC) | √(M1/M3/M4) | |
| app/core/stages.py | | | √ | | √ | (测试对象) | | | √(H-11 钉) | | | √ | √ | √ | √ | √ | √ | √(G1/G2/G3/G6/G7) | √(P1/P3 挂点) | | | √(B7qw) | | | √(OC) | | |
| app/llm/client.py | | | | | | | | | | | | | | | | | | √(G2 识别已并) | | | √(A4) | √(B1/B2) | | | √(OD10) | | |
| app/deslop.py | | √(豁免) | | | | | √(B5b 搬) | | | | | | | | | √(卡6) | √(卡7) | | √(P4 旁) | | | | √(C2) | | | | |
| app/core/gates.py | | | √ | | | | | | | | | | √ | | | √ | | √(G1/G7) | √(P4) | | | | | | | | |
| app/core/co_dialogue.py | | √ | √ | | | | √(B5c 邻) | √ | | | √ | | | √ | | √ | | | √(P1/P2) | √ | | | | | | √(M1 邻) | |
| app/config.py | | | √ | | | | | | | | | | √(新键) | | | | | √(G1/G3 新键) | | | | | | | | | |
| app/core/co_writing.py | | | | | | | | √ | | | | | √(cw 字段) | | | | | | | | √(A 组) | | | | | √(M1) | |
| app/update_check.py / update_install.py | | | | | | | | | √ | | | | | | | | | | | | | | | √(UA/UC/R3) | | | |
| tools/installer.iss / scripts/build_release.py | | | | | | | | | | | | | | | | | | | | | | | | √(UA/MSCH) | | | √(DOC-10/D3) |
| app/ui/qml/PipelinePanel.qml | | | | | | | | | | | | | | | | | | | | | √(A2) | | | | | | |
| app/ui/qml/components/CwDialogueDock.qml | | | | | | | | | | | √(F3) | | | | | √(卡6 指标条) | | | | √(卡4/卡10) | √(A6) | | | | | √(M1) | |
| app/prompts/writing.py + skill_rules.py | | | | √(B2c) | | | | | | | | | | | | √(卡6M) | | | | | √(A11 邻) | | | | | | |
| app/core/memory.py | | | | √(B2d 邻) | | | | | | | | √ | | | | | | | √(P2) | | | | √(C3) | | | | |
| app/core/l0_checks.py | | | | | | | | | | | | √ | √ | √ | √ | | | | | | | | | | | | |
| app/core/orchestrator.py | | | | | | (测试对象) | | | | | | | | | | | | √(G3/G4/G6) | | | | | | | √(OC) | | |
| app/core/state.py | | | | | | | | | | | | | | | | | | √(G5 键) | √(P3 旁) | | | | | | | | |
| app/usage.py | | | | | | | √(B5c) | | | | | | | | | | | √(G5) | | | | | | | √(OB-cost) | | |
| README.md / README.en.md / latest.json | | | | | | | | | | | | | | | | | | | | | | | | √(MSCH/UDOC) | | | √(D 组/DOC-4/I18N) |
| tests/unit/test_cw_bridge_slots.py | | | | | | | | √(宿主) | | | √(三组) | | | | | | | | | √(共享) | | | | | | | |

---

## 三、冲突矩阵（核心：同文件 ≥2 任务逐对裁决）

全局合并策略（引用 w4_refactor_plan §四/§B8 + w5_f123_fix §4，对所有批次生效）：
1. **Mixin 策略**：B8 各 mixin 只搬方法实现，全部 Signal/Property 留 Bridge 主类声明区（968-976 一带）——QML context property 与信号接线零改动；
2. **方法名锚纪律**：凡与 B8 时间重叠的 bridge 落点任务，PR 描述一律用符号锚（`newProject`/`startPipeline`/`installUpdateNow`…），review 按符号不按行号；
3. **先落后搬**：某文件同时被「功能/快赢批」与「搬迁批（B5/B8）」触及时，功能批先落、搬迁批整体平移（shim 保证调用方零改动）；
4. **纯搬运 PR 与语义 PR 不同时 open**：B3 是纯搬运，卡3/卡5/E1 等语义批在其后串行 open。

### 3.1 app/ui/bridge.py（最大热点，6249 行，≈20 个任务触及）

| 任务对 | 冲突性质 | 施工先后 | 合并策略 |
|---|---|---|---|
| QW-A1/A2/A3（newProject/startPipeline）× B8 全系 | 保留层 vs 切分：两方法**任何 mixin 都不搬**，无文件级搬家冲突 | A1-A3 先行（快赢 P0） | 仅行号漂移问题→符号锚；A2 新增 `startCta`/`gotoCwStage` 的 Property/Signal 放主类声明区 |
| QW-A5-A8（共写族）× B8e | 同区域（共写族 ≈600 行 = B8e 搬运体） | QW-A5-A8 先落，B8e 后搬 | 符号锚（`setCwUnitRange`/`_on_cw_sum_done`/`generateCwDraft`）；新增 Signal 全进主类声明区，搬运零拆改 |
| 卡1（F1-F3）× B8e | **同方法**（supervisor 族+_dispatch_cw_rewrite 正是 B8e 的 ≈600 行） | **顺序钉死：卡1 先落 → B8e 后搬** | 卡1 已示范：Signal `supervisorAttentionChanged` 放 972 行旁、旗标放 1089 行旁、mixin 只搬方法体；宿主测试 test_cw_bridge_slots.py 即 B8e 的回归网 |
| 卡1 × QW-A6-A8 | 同文件不同方法（卡1 在 4756-4933；A6=4361、A7=4116、A8=5123） | 并行可（w5_f123 §4-4：零 hunk 交叠） | 行号漂移互知即可；同批若同周，A 组先 rebase 卡1 |
| 卡10 × 卡1 × B8e | 同链（CW-G1~G3=卡1；余四条在 4402/4259/1312/5227） | 卡1 → 卡10 → B8e | 卡10 的 CW-G5 token 化触碰所有 cw worker done/error 槽——必须在 B8e 前定型，避免搬两次 |
| U-A/U-B/R3 × B7 × B8b | 同方法链（installUpdateNow 2095-2141） | **顺序钉死：B7 补测 → U-A/U-B/R3 功能 → B8b 整体平移**（w4 §四原文） | 跳过 B7 直接动 installUpdateNow = 在 22% 覆盖路径裸奔；U-A 探针新断言就是 B8b 专项回归网 |
| OA/OB-cost（设置/统计新节）× B8d | 同区域（设置域/统计面板 5419+） | **OA 先于 B8d**：新面板做成独立 controller 类挂 bridge，B8d 搬 settings 域时不动 controller | w4_model_orch §五原文「别再往大文件里摊」——controller 化是硬规约 |
| QW-B2（H-7 设置域）× B8d | 同域不同方法（降级回执 vs saveConnection/setSlot） | QW-B2 先行 | 符号锚；B8d 搬时顺带平移 |
| QW-A11（_ui_tool_dispatch）× B8 | 未归域薄壳（w4 §3.3-6：留给 B8e 后任意窗口） | 任意 | 改它不增加搬运成本，符号锚即可 |
| OB-M1/M3/M4 × B8e / 保留层 | M1 落共写族（B8e 区）；M3/M4 落 Bookshelf+connReadySummary（保留层邻） | OB-M 批在 Wave 3，B8e 在 Wave 2——**B8e 先搬，OB-M 落在 mixin 上** | M3 的 `connReadySummary()` 复用 QW-A5 的 `_slot_readiness`，两批共享函数签名 |
| 卡9-P1/P3 挂点（_do_lock_chapter 4565/_run_backflow 接线）× B8e | P1 共写首挂点在 MemoryBackflowWorker（core），bridge 仅接线 | 卡10-CW-G6 → P1 → 挂点；均在 B8e 后落在 mixin | 对账逻辑放 core（fact_ledger.py），bridge 只留 1-2 行接线，天然符合分层 |
| B6 × 卡1 × 卡10 | **同宿主测试文件** test_cw_bridge_slots.py | 卡1 三组测试先写（当前即红），B6 状态机组与卡10 红测随后并入 | 共享 `_SlotSelf`/`_DispatchSelfMode` 替身；替身签名随生产码同步扩参（F2 教训） |

### 3.2 app/core/stages.py（第二热点，3727 行）

| 任务对 | 冲突性质 | 施工先后 | 合并策略 |
|---|---|---|---|
| B3 × 卡3（finalize 写点 2235-2248）× 卡8-G1（1819 后）× 卡8-G6（2233-2248）× 卡7（2009-2013）× 卡6S（1956/2013/2034） | **同函数**（全部在 microcycle 862 行体内） | **B3 必须先行**（卡3 硬前置；G1 若 B3 未完成则顺延或作为 `_mc_word_gate` 首个语义 PR；卡7/卡6S 的挂点 B3 后落在 `_mc_deslop`/`_mc_scan`） | B3=纯搬运 PR；语义批串行 open；卡6S 可先落 deslop.py/gates.py 侧纯逻辑（scan 契约 `scan_text(text)->list[Finding]` 不变），接线等 B3 |
| 卡2 × B3 | 同文件**不同区段**（细纲批 1101-1330 与 review_l0_block 2413+ 均在 microcycle 区段外） | 卡2 在 B4 后即可动工，**不被 B3 阻塞**，可与 B3 并行 | git 可并行；两 PR 不同时 open 审查；若卡2 需在 G4 门/落库区加挂点，等 B3 落在 `_mc_assemble/_mc_finalize` |
| 卡3 × 卡4（细纲字段/解析/审校回写）× 卡5 | 同区段（planning 解析 1159+、FINAL_REVIEW 解析、craft_block 1754） | 卡3 → 卡4（卡4 的 supervisor 对账依赖卡1，天然串行）→ 卡5（共享卡3 账本基建，同批） | ⚠ 接线护栏 `test_satisfaction_engine.py:191-199` 钉死注入点计数（正文 3 处/细纲 2 处）——**卡3/卡4/卡5 任何注入点变化必须显式改钉值并跑该测试**；W0c 钉测 `test_cw_prose_check.py:95-101` 同理（两档 prompt 共用） |
| 卡8-G3（2177-2186）× B3 | need_human 升级点在 microcycle 体内 review 区段 | B3 后落在 `_mc_review` | 符号锚 `mark_chapter_need_human` |
| 卡2/卡3 注入 × test_outline_partial_batch / probe_prompt_baseline | 提示词面 | 任何 stages 装配批必跑 `tests/probe_prompt_baseline.py` | S1/S4/A/B 字节隔离纪律：开关关=字节不变（`test_ledger_off_byte_identical` 形态） |
| QW-B7（H-11 契约钉 3128/bridge:279）× 卡9-P1 | 同文件不同区段（3128 在 canon 审计区） | 无冲突，随时 | 纯测试面 |

### 3.3 app/llm/client.py（全仓覆盖最好，低冲突）

| 任务对 | 冲突性质 | 施工先后 | 合并策略 |
|---|---|---|---|
| QW-B1（_stream_messages/_retry_wait/clean_llm_output 四件）× QW-A4（test_connection 787） | 同文件不同函数 | 并行安全；若同批，一次 PR 分两个 commit | QW-B1 一次动 `_stream_messages`，顺手带 E 识别层 `last_finish_reason`（w4_model_orch §D/§E 共享改造点裁定） |
| QW-B1 × QW-B2（client.py:313 降级备忘录） | 同文件不同函数（242-259 vs 307-323） | 并行 | hunk 分离，无语义交叠 |
| QW-B1 × 卡8-G2 | G2 消费层在 stages，识别层已并入 QW-B1 | QW-B1 先 | G2 拦截逻辑零 client 改动 |
| OD10 × QW-B1 | 同文件（providers/client 探测） | OD10 在 Wave 2 | 无交叠 |

### 3.4 其余热点（逐对从简）

| 文件 | 任务对 | 冲突性质 | 先后与策略 |
|---|---|---|---|
| app/deslop.py | B1(删 summarize_findings) × 卡6S(复活) | **互斥裁决** | **以卡6S 为准豁免该函数**（w5_quickwins §五-7 裁决）：B1 删 8 留 1，并在卡6S 落地前于函数头加注释防误删 |
| app/deslop.py | 卡6S/M × 卡7(findings_to_prompt_text 390-398) × B5b(搬迁) | 同文件同区段+搬迁面 | 卡6S → 卡7 → B5b 整体平移（shim 并行安全）；卡6M 的 lieflat 切片同步（writing.py:214-240 三消费点）与 B2c 先拆环后动 |
| app/core/gates.py | B2a(:82-83 改 import) × 卡6S(to_record:38) × 卡8-G7(:131-160) × 卡9-P4(新函数) | 同文件不同函数 | B2a 最先（纯 import 改写）；其余全为新函数/独立函数，方法名锚并行；P4 的 check_collapse 与 word_count_precheck **语义分离**（55% 故障闸 ≠ 90% 质量闸，原型坑②） |
| app/config.py | B2a(re-export) × 卡3(satisfaction_ledger 新键) × 卡8-G1/G3(word_overflow_breaker/consecutive_fail_pause 新键) | 同文件不同区段 | B2a 先行；其余都是追加新键，天然无 hunk 冲突；G1 的 N 必须**可配**（文青书 P90 已 >5×） |
| app/core/co_dialogue.py | 卡1(:453 后新函数) × 卡10(:529-537 半提交) × 卡6S(:619,639 指标对比) × B1(:60 clear_transcript) × 卡9-P1(:744) | 同文件多函数 | 卡1 → 卡10 串行（同链）；卡6S/B1/P1 不同函数可并行；B5c 搬 dialogue_log 时 co_dialogue 的 import 由 shim 兜住 |
| app/core/memory.py | 卡2(:73 升级) × 卡9-P2(build_state_card) × B2d(han_tokens 邻域) | 同邻域不同语义 | w4 §3.2 同款判定：git 并行、语义审查串行；卡2 签名不变（四消费方自动受益） |
| app/prompts/writing.py+skill_rules.py | B2c(拆环) × 卡6M(DESLOP_REWRITE_PROMPT 切片) × 卡4(STYLE_DISCIPLINE) | 同文件同模板区 | B2c 先拆环；卡6M 改 DESLOP_REWRITE_PROMPT 必须同步 lieflat 三消费点切片；卡4 只动承接铁律一行 |
| tools/installer.iss + scripts/build_release.py | U-A(iss 两处) × M-SCH(build_release 回填) × QW-D3(第 7 闸) × DOC-10(HTML 打包) | 同文件不同区段 | 全部独立小改，符号锚；M-SCH 在质量闸门后插 collect（顺序已是 :404-434，插两行） |
| app/ui/qml/PipelinePanel.qml | QW-A2(startButton:379) | 单任务+联动 | 改前全仓 grep `startButton`（tests/+assets/demo/script.json:58 联动）；`probe_qml_compile.py` 必跑 |
| app/ui/qml/components/CwDialogueDock.qml | 卡1(:150-170) × QW-A6(:348,384) × 卡4(钩型登记卡) × OB-M1(示例卡片) | 同文件不同组件块 | 卡1 → 卡4 → OB-M1 时序天然（Wave 0→3）；A6 独立并行 |
| app/core/state.py | 卡8-G5(anomalies 键:366) × 卡9-P3(:403 旁独立通道) | 同文件键表 | 都是 validate_state 键型表追加，串行一天内完成 |
| app/update_check.py | QW-B3/B7(U-2 :462-463) × U 线 | 同函数 | U-2 修复随 B7 批一起做（w5_update §5.2-B 裁定），U-A 不再动 check() |
| README.md/README.en.md/latest.json | QW-D1-D4 × M-SCH × UDOC × I18N × DOC-4 | 同文件多段 | 纪律：**先装 check_docs 报警器（D3），再修数（D2/D4）**；latest.json 版本行在 M-SCH 后由构建回填；DOC-4 首屏重构在 Wave 3 前不做大改 |

---

## 四、统一 DAG（依赖=报告声明+冲突推导）

### 4.1 DAG 主干（箭头=必须先完成）

```
B0 ──┬─→ B4 ──┬─→ B3 ──┬─→ 卡8-G1(E1) ─┬─→ 卡8-G2
     │        │        ├─→ 卡3-T1 ────┼─→ 卡5-T5(Wave4,版权裁决)
     │        │        ├─→ 卡8-G6 ────┴─→ OC 批量挂机(与G3/G5汇)
     │        │        └─→ 卡7(弱,B3后落_mc_deslop)
     │        ├─→ 卡2-T3(E3) ──→ 卡9-P3(还需P1) 
     │        ├─→ 卡8-G3(E2) ──→ OC
     │        ├─→ 卡8-G4/G5/G7 ──→ OB-cost(B方案,需G5) 
     │        └─→ H4 ──→ OC
     ├─→ 卡1(B6宿主) ─┬─→ 卡4-T2 ─→ 卡5
     │                ├─→ 卡10(CW-G4~G7) ─→ 卡9-P1 ─→ 卡9-P3
     │                └─→ B8e(最后)
     ├─→ B7 ─→ U-A ─┬─→ U-B ─┬─→ B8b(最后)
     │              └─→ R3 ──┘  └─→ UDOC
     ├─→ QW-A1..A9(轨道) ─→ OB-M1(还需卡1后共写稳定)
     ├─→ QW-B1(容错) ─→ 卡8-G2
     ├─→ QW-D3(报警器) ─→ QW-D2/D4(修数) ─→ DOC-4 ─→ DOC-8/9/10
     ├─→ B1(删8,卡6豁免) 
     ├─→ B2a/B2c/B2d(拆环) ─→ B5a/B5b/B5c(搬屋,插队)
     ├─→ 卡6S ─→ 卡6M ─→ (B5b 平移)
     └─→ OA(阶段路由) ─→ B8d(B8 系列内部 a→b/c/d, e 最后)
BACKUP(独立)  M-CI/M-SCH(独立)  SKILL(独立)  OD10(独立)  U-C(先行可)
```

### 4.2 关键路径与路径人日

| 路径 | 链 | 工程人日 |
|---|---|---|
| **P-账本（关键路径）** | B0(0.5) → B4(2) → B3(3.5) → 卡3-T1(4.5) → 卡5(5) | **≈15.5** |
| P-挂机 | B0(0.5) → B4(2) → B3(3.5) → G3(0.5) → G6(1.5) → OC(7) | ≈15 |
| P-共写纵深 | B0(0.5) → 卡1批(2.5) → 卡4(4) | ≈7；+卡10(4)→卡9-P1(3)→P3(3) ≈ **17**（Wave 2-4 跨度；R1 勘误 17.5→17） |
| P-更新链 | B0(0.5) → B7(1) → U-A(2.5) → U-B(0.5) → R3(2) → UDOC(0.5) | ≈7 |
| P-文档 | D3(0.5) → D2/D4(0.75) → DOC-4(2) → DOC-9/10(4) | ≈7.25 |

**单点闸门排序**：B3（3.5d，被卡3/G1/G6/卡7/卡5 五线依赖）> B4（2d，被 B3/卡2/G3/G4/G5/G7/H4 依赖）> 卡1（2d，被卡4/卡10/B8e 依赖）> B7（1d，被 U 线全链依赖）。**任何一天开工的最大忌讳：跳过 B4 动 stages、跳过 B7 动 installUpdateNow、在 B3 前往 microcycle 体内塞挂点。**

### 4.3 Wave 映射与总账

| Wave | 内容 | 人日 |
|---|---|---|
| **0（第 1-2 周）债+快赢** | B0、B4、B3、B7、B1(删8)、B2a/c/d；QW-A1-A10、A11(C12b)、B1、B2、B5(M-CI)、B6(M-SCH)、B7(H-11)、B8+D4、C 组外全部 D 组(D1-D9)、I18N、U-C | 债 8-8.75 + 快赢 ≈13-15 = **21-24**（蓝图口径 19-20，差额=D5/D6/D9 可滑窗；A11 已立卡 C12b） |
| **1（第 3-4 周）引擎第一批+0.21 发版** | 卡2(T3)、卡6S、卡9-P2/P4、卡8-G1/G3、PROMO、发版运营 | **6.5-8.5** |
| **2（第 5-8 周）双形态+编排+静默安装** | U-A/U-B/R3/UDOC、卡7、卡8-G2、卡10、OA、OD10、SKILL-S/ML、BACKUP、B2b(C10b)、B5a-c、B8a-e（插队）、B6 余量 | **25-32** |
| **3（第 9-12 周）纵深第二批+清账** | H4、卡3-T1、卡4-T2、卡6M(C16b)、卡8-G4/G5/G6/G7、OC、OB-cost、卡9-P1/P3、DOC-4/8/9/10、OB-M1-M4(L1 缓) | **46.5-53.5**（R1 直加复算勘误） |
| **4（第 13 周+）占位** | 卡5-T5（版权裁决②）、爽点盲评 A/B（裁决①，花钱）、T3 v3 预注册长跑、1.0 判据收口 | 5-7 + 待裁 |
| **合计（不含盲评/运营/待裁）** | | **≈100-122 人日**（其中插队件 B5/B8 共 10d 不占功能窗口） |

---

## 五、批次卡（可独立验收施工批）

> 通用前置（C01 落地后每批复验）：`./.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider`（基线 1132+ 全绿）与 `./.venv/Scripts/python.exe scripts/dep_graph.py`（边数/SCC 不升）。每批 PR 描述必填：行为保持性声明、验证命令与期望值、回滚边界、QML 信号槽面「零变化」承诺。回滚统一默认：**单提交或提交序列 revert 到上一绿点**，下文只写特殊回滚。

### Wave 0

**C01 基线冻结**（B0｜0.5d｜前置：无）
- 文件：新增 `scripts/dep_graph.py`、`scripts/static_scan.py`（自 `_scratch/superiter/scripts/` 迁入）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider`（记录通过数）；`./.venv/Scripts/python.exe scripts/dep_graph.py`（记录 core->app-top=42、SCC=3）
- 回滚：删除两脚本。

**C02 run 测试网+microcycle pin**（B4｜2d｜前置：C01）
- 文件：新增 `tests/unit/test_orch_run_smoke.py`（5 路径：全绿 done/G1 回退/G9 同章重跑/中停/异常 dump）、`tests/unit/test_microcycle_steps.py`（7 步 pin）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit/test_orch_run_smoke.py tests/unit/test_microcycle_steps.py -v -p no:cacheprovider`
- 发现 bug 登记不顺手修；零生产码。

**C03 文档止血**（QW-D1/D2/D3/D7/D8｜1.35d｜前置：无，D3 先于 D2）
- 文件：`docs/hero_cw.png`（hero 位换 `docs/shot_pipeline.png`，已确认存在）、`README.md:20,46,383`、`latest.json`、`scripts/check_docs.py`(新)、`.github/workflows/tests.yml`、`scripts/build_release.py`(第 7 闸)、`CHANGELOG.md:1229`
- 验收：`./.venv/Scripts/python.exe scripts/check_docs.py` 绿；临时改坏一个数字验红；`cmp docs/hero_cw.png docs/shot_co_writing.png` 不再 IDENTICAL
- 回滚：各文件独立 revert。

**C04 EN 同步+H-18**（QW-D4/B8｜0.5d｜前置：C01）
- 文件：`README.en.md:354,378,384,451`
- 验收：`./.venv/Scripts/python.exe scripts/check_docs.py` 对 EN 同绿；`grep -n "V4 Pro" README.en.md` 零命中。

**C05 LLM 容错四件套**（QW-B1｜1.25d｜前置：C01）
- 文件：`app/llm/client.py`（`_stream_messages:606` 加 `<think>` 流式状态机+`last_finish_reason`；`_retry_wait:242` 读 Retry-After；`clean_llm_output:844` 加 stripThinkBlocks；非流式地板 2048；finish_reason 三条人话）；新增 `tests/unit/test_think_filter.py`
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "client or payload or think" -q -p no:cacheprovider`；过滤器四态（`<think>`/`<Think>`/半截标签 holdback/未闭合丢弃）单测逐字对拍 easy-writing；新建断言：假流式 length 停止 → `last_finish_reason=='length'`
- 回滚：单 PR revert（client.py 是全仓覆盖最好模块，行为面=新增过滤，关字面量即可退）。

**C06 撞墙修复组**（QW-A1/A2/A3/A4/A5｜2.5d｜前置：C01；改 startButton 前全仓 grep）
- 文件：`app/ui/bridge.py:1292-1294`(toast 分支)、`1395-1407`(missing 加 `conn.get("model")`)、新增 `_slot_readiness()`；`app/llm/client.py:787`(黄牌)；`app/ui/qml/PipelinePanel.qml:379`(CTA 分支)；`app/ui/qml/SettingsPanel.qml:293`(琥珀徽标)；`assets/demo/script.json:56-58`；新增 `tests/unit/test_slot_readiness.py`（断言共写/自动档 toast 文案、missing[] 双报、黄牌文案、零网络请求）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "slot or readiness or conn" -q`；`./.venv/Scripts/python.exe tests/probe_qml_compile.py`；`grep -rn startButton tests/ assets/demo/ | wc -l` 联动核对
- 回滚：QML 一文件 + bridge 一 hunk，独立 revert；自动档行为零变化由现有 UI 测试兜底。

**C07 共写轨道补全**（QW-A6/A7/A8/A9｜1.25d｜前置：C06）
- 文件：`app/ui/qml/components/CwDialogueDock.qml:348,384`、`app/ui/bridge.py:4361`(setCwUnitRange 即时校验)、`:4116-4118,4319-4321`(自动开章+兜底文案)、`:5123`(_on_cw_sum_done 预告表)、`app/ui/qml/components/WizardDialog.qml`、bridge 新增 `connReadySummary()`
- 缺口 G1：A7 的阶段切换钩子需先定位真实实现（`cwStageChanged` Property 1224，无 `_on_cw_stage` 方法）——施工首小时完成定位并回填本卡
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "cw or wizard" -q`；`./.venv/Scripts/python.exe tests/probe_qml_compile.py`；新建断言：范围超 ±10 即时 warn 零请求；阶段预告五文案表逐字断言
- 回滚：纯文案+预填级，单 commit revert。

**C08 共写实伤修复 F1-F3（含 B6 宿主前三组）**（卡1=QW-A10｜2d｜前置：C01）
- 文件：`app/ui/bridge.py`（删 4845-4857 活版；4933 加 `mode="compose"`；972/1089 加 attention Signal/旗标；4859 痕后置；4790 留痕分口径 skipped/overridden）、`app/core/co_dialogue.py:478` 后新增 `supervisor_report_has_conclusion`、`app/ui/qml/components/CwDialogueDock.qml:150-170`、`tests/unit/test_cw_prose_check.py:148`（桩扩 mode 形参）、新增 `tests/unit/test_cw_bridge_slots.py`（F1 inspect 钉测+F2 compose 钉测+F3 四测）
- 先写哪条：`test_f1_supervisor_defined_once_with_c2_wiring`（当前即红，红转绿=F1 完成）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "cw" -q -p no:cacheprovider`；`./.venv/Scripts/python.exe tests/probe_qml_compile.py`；`./.venv/Scripts/python.exe tests/probe_needs_fix.py`（toast 口径核对）；手工 401 场景见 w5_f123 §1.4/§2.4/§3.4 三套用户可见判据
- 回滚：三个 commit（F1/F2/F3）独立 revert；demo_director 已核对无冲突。
- 冲突提示：**本批先落，B8e 后搬**；与 C07 零 hunk 交叠。

**C09 更新链铺路**（B7+M-CI+M-SCH+U-C+U-2 修复｜3d｜前置：C01）
- 文件：新增 `tests/unit/test_update_install_flow.py`（download/resume/哈希失败/U-1 毒化钉子/updateState 离屏分支）；`scripts/check_manifest_consistency.py`(新)+GH Actions release-consistency job+`docs/release_checklist.md` 加行；`scripts/build_release.py`(stats/installed_size 回填+notes 去数字+CI 断言双写相等)；`app/update_install.py`(U-C 清理函数)；`app/update_check.py:462-463`（未验签不写缓存+不短路）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "update" -q -p no:cacheprovider` 全绿；`./.venv/Scripts/python.exe tests/probe_update_ui.py` 46 项全过；`./.venv/Scripts/python.exe scripts/check_manifest_consistency.py` 对 0.20.x 实跑出三通道比对表；新建断言：updates/ 三份 setup → 下载成功后剩两份
- 回滚：四个子件各自独立 revert。

**C10 结构债插队：B1+B2 子批**（B1+B2a/B2c/B2d｜1.5d｜前置：C01；与 C05 同周可）
- 文件：见台账 §1.1（注意 summarize_findings 豁免+函数头注释）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider`；`./.venv/Scripts/python.exe -m pytest tests/unit -k "volume or compaction or skill or wb or config or prompt" -q`；`./.venv/Scripts/python.exe scripts/dep_graph.py`（§2 SCC 期望 0；core->app-top 期望 42-5=37）；`./.venv/Scripts/python.exe tests/probe_prompt_baseline.py`
- 回滚：四个子批各自提交独立 revert；环 3 抖动先回 B2d。

**C11 microcycle 切七阶段（可拆两段各 1.75d）**（B3｜3.5d｜前置：**C02**）
- 文件：`app/core/stages.py:1547-2408` 单文件
- 步骤：`_MicroCycle` dataclass（18 字段）→ 逐段 `_mc_assemble/_mc_draft/_mc_word_gate/_mc_scan/_mc_deslop/_mc_review/_mc_finalize`，每迁一段跑 pin 测试，**禁止一次全搬**
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit/test_microcycle_steps.py tests/unit/test_orch_run_smoke.py tests/unit/test_orch_volume_persist.py tests/unit/test_chapter_resume.py -q -p no:cacheprovider`；`-k "stages or micro or resume or outline or payload or phase"`；`./.venv/Scripts/python.exe tests/probe_prompt_baseline.py`；`./.venv/Scripts/python.exe scripts/dep_graph.py`（无新违规）
- 回滚：AST 对比拆分前后函数局部赋值集（脚本化核对）；整批一个提交序列，任何一步红 revert 到上一绿点。

**C12 信任残渣+i18n+版权夹具**（QW-B2/B7/I18N/D9｜1.5-2d｜前置：C01）
- 文件：`app/ui/bridge.py`(设置域,符号锚)+`app/llm/client.py:313`(H-7)；新增契约钉测试（stages.py:3128 写侧/bridge.py:279 读侧，任一侧格式单方面改动即红）；`README.md`(i18n 声明行，落点见缺口 G9)；`tests/` 夹具改名（斗破专名/守夜人作者）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "contract or degrade or copyright" -q`；主仓 `grep -rn "萧炎\|乌坦城\|爱潜水的乌贼" tests/` 零命中（《守夜人》系自创虚构书名按裁决保留，仅作者名改虚构）
- 回滚：三件独立。

**C12b w1_ux 小修四件**（QW-A11｜0.5-1d｜前置：C01）
- 文件：`app/core/agent_tools.py`（tooltip 虚标/「去一下AI味」漏「一下」/read_chapter 误吃当前章规则序）、`app/ui/bridge.py:4155`(_ui_tool_dispatch Console 话术错位)、回归跑 `_scratch/superiter/tests/probe_parse_instr.py`
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "agent_tools or ui_tool" -q`；probe_parse_instr 全绿
- 回滚：单 commit revert。

**C13 排障页+索引页**（QW-D5/D6｜1.25d｜前置：C03）
- 文件：`docs/排障_v1.md`(新，13 条文案逐字抄自 `app/llm/client.py:461,551,795-815`/`app/ui/bridge.py:2649` 等)、`docs/README.md`(新)
- 验收：`./.venv/Scripts/python.exe scripts/check_docs.py` 检查 3/5 绿（对照表 ≥10 条且每条文案可在 app/ grep 到）

### Wave 1

**C14 T3 伏笔到期引擎**（卡2=QW-E3｜1.5-2d｜前置：C02）
- 文件：`app/core/tracking_store.py`(+parse_recovery_window/foreshadow_urgency/「已失效」态)、`app/core/memory.py:73`(排序注入，签名不变)、`app/core/l0_checks.py`(+foreshadow_findings)、`app/core/stages.py:1101`(细纲批后 fail-open 校验)、`:2433+`(review_l0_block 并列注入)、`record_event` 告警；新增 `tests/unit/test_foreshadow_urgency.py`
- 验收：新建断言 `"第40-45章"→(40,45)`、`"第N单元"→(None,None)`；超期排最前带【超期】前缀；批次 L0 对超期必排期；`./.venv/Scripts/python.exe tests/probe_prompt_baseline.py`（字节面）
- 冲突：与 C11(B3) 同文件不同区段可并行，两 PR 不同时 open；与 C15(C3 状态卡) 语义审查串行。

**C15 状态卡+P4 质检**（卡9-P2/P4=QW-C3/C2｜2d｜前置：C01）
- 文件：`app/core/memory.py`(+build_state_card) 或新 `app/core/state_card.py`；`app/core/gates.py`(+check_collapse)、`app/deslop.py` 旁(+repeat_check)、`assets/sensitive_words.txt`(新)、`app/core/co_dialogue.py:156`(消费)；新增 `tests/unit/test_state_card.py`、`test_collapse_gate.py`
- 验收：压力样本裁剪后 ≤12288B 带审计日志；1382/3000=46% 触发 crash 信号而 90% 闸不联动（两闸分离断言）；`pytest -k "state_card or collapse" -q`
- 冲突：与 B2d 同邻域（git 并行、语义审查串行）；check_collapse 与 word_count_precheck 语义分离不合并。

**C16 deslop 度量层 S 档**（卡6S=QW-C1｜1.5d｜前置：C01）
- 文件：新增 `app/deslop_metrics.py`；`app/deslop.py:378`(复活 summarize_findings+trailer 收窄 600 字窗)、`app/core/gates.py:38-46`(to_record 扩 metrics)、`app/core/co_dialogue.py:619,639`(before/after 升级)；新增 `tests/unit/test_deslop_metrics.py`
- 验收：≥10 类毒文本命中 ≥9 类且 metrics 与手算一致；正文中段「没人知道」不报、文末仍报（窗口断言）；`pytest -k "deslop" -q`
- 冲突：接线落 stages 等 C11 完成后（`_mc_scan/_mc_deslop` 清晰位）；B5b 搬时整体平移。

**C17 G1 字数断路器**（卡8-G1=QW-E1｜1d｜前置：**C11**）
- 文件：`app/core/stages.py:1819` 后（B3 后落在 `_mc_word_gate`）+ trim 最低压缩量守卫（:1924 采纳处，压缩量 < cut_pct/2 视为失败）+ trim_over 升 error；`app/config.py`(word_overflow_breaker，N 可配)；新增 `tests/unit/test_word_overflow_breaker.py`
- 验收：假客户端 10 倍稿 → 后续 rewrite/审校调用数=0、record 带 word_overflow；trim 等长稿被拒；`pytest tests/unit/test_word_overflow_breaker.py -q`
- 备注：若 C11 延期，本卡降级为「纯逻辑+单测先行，接线挂 _mc_word_gate」。

**C18 G3 跨章断路器 + 0.21 发版准备**（卡8-G3=QW-E2｜0.5d+窗口｜前置：C02）
- 文件：`app/core/orchestrator.py:486-496`(连续 needs_fix 计数→auto_pause，sig 带章号区间，只触发一次)、`app/core/stages.py:2177-2186`(need_human warn 升 error)；新增 `tests/unit/test_consecutive_fail_pause.py`；PROMO 防腐 pass；发版 checklist 重走
- 验收：连续 3 章 REJECT-HARD → paused 且只触发一次；pass 即清零；`pytest tests/unit/test_consecutive_fail_pause.py -q`；`./.venv/Scripts/python.exe -m pytest tests/unit -q` + 六道发版闸门（`probe_prompt_baseline`/`probe_qml_compile`/`tools/audit_tokens.py`/`scripts/update_keys.py --check-repo`/`probe_update_ui`/`probe_conn_delete`）

### Wave 2

**C19 静默安装 U-A**（U-A｜2.5d｜前置：C09(B7)；**B8b 之前**）
- 文件：`tools/installer.iss`（[Run]:66 去 skipifsilent；[Code] 加 CurStepChanged 写 `{app}\.update_done`）；`app/ui/bridge.py:2095-2141`（flush_draft→journal→shutdown()→startDetached(`/SILENT /NORESTART /LOG=`)）；`app/main.py:137` 旁（journal×marker 对账+「上次更新没有完成」出口）
- 验收：`tests/probe_update_ui.py` 新断言（monkeypatch QProcess.startDetached 捕获参数含三旗标+journal 落盘）；发布机 `setup.exe /SILENT /LOG` 装完 `.update_done` 存在；VM 矩阵 0 向导点击
- 回滚：iss 两处独立还原；app 侧 journal 逻辑单 commit。

**C20 一键合并 U-B**（U-B｜0.5d｜前置：C19）
- 文件：`app/ui/qml/components/UpdateDialog.qml`、`app/ui/bridge.py`、`tests/probe_update_ui.py:289-292`（断言改「单击+倒计时取消可达」）
- 验收：倒计时取消后 `_quit_for_update` 保持 False、已验包保留；探针全绿。

**C21 引导回滚 R3**（R3｜2d｜前置：C19；可与 B8b 并行）
- 文件：新增 `app/update_rollback.py`（journal first_run 相位+dump mtime 崩溃判定+恢复对话框）；`app/ui/bridge.py`(接线)、`app/ui/qml/Main.qml`(横幅)；新增探针（伪造 journal+新 dump → 对话框出现且 startDetached 参数正确）
- 验收：探针绿；VM：人为首启崩溃→恢复框→旧包走向导回滚成功。

**C22 更新链文档收尾**（UDOC｜0.5d｜前置：C19/C20/C21）
- 文件：`README.md:91,96`（4 在线+2 本地口径；「全程不用离开应用」此时才成立）、`docs/排障_v1.md` 更新条目
- 验收：`./.venv/Scripts/python.exe scripts/check_docs.py` 绿。

**C23 must 复扫闭环**（卡7｜1-1.5d｜前置：C16 弱；C11 后落 `_mc_deslop` 更稳）
- 文件：`app/core/stages.py:2009-2013`(采纳前双复扫，新增违规→rollback_to+并入 max_deslop_rounds 熔断)、`:2024-2040`(G7 对账断言)、`app/deslop.py:390-398`(findings_to_prompt_text 带规则 ID)、3-gram 防复用；新增 `tests/unit/test_deslop_must_rescan.py`
- 验收：初稿 0 违规+改写稿引入 forbid → 改写稿被回退、复扫日志含「must 新增违规」、轮次递增；无 must 规则 → 字节不变断言。

**C24 G2 截断拦截**（卡8-G2｜1d｜前置：C05+C17）
- 文件：`app/core/stages.py`（prose/trim/deslop 相位读 `last_finish_reason`，length 稿按 G1 处理不进闸门链）；新增测试：假流式 length → 调用数断言=0、章标 truncated；stop 正常 → 零行为变化。
- 验收：`pytest -k "truncate or finish" -q`。

**C25 CW 护栏余四条（拆两段）**（卡10｜3.5-4.5d｜前置：C08；B8e 之前）
- 段1（1.5d）：CW-G4（`bridge.py:4499` 锁定闸上限入账+`_start_cw_outline_validation:4402` 截断到最新批±2）+ CW-G7（`_rollback_to:5227` 打回确认卡+清 supervised/auto_fix）；新增 `tests/unit/test_cw_state_machine.py`（含缺口4 两 save 崩溃一致性、缺口5 打回×已锁定章）
- 段2（2-3d）：CW-G5（`_cw_cancelled`→worker 代际 token，`co_dialogue.py:529-537` 半提交对账回执）+ CW-G6（`_open_project:1312`/锁定时扫「已锁定∧¬backflow_is_fresh」→横幅+一键补跑）
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -k "cw" -q`；`tests/probe_cw_state.py`/`probe_cw_stage_persist.py`/`probe_cw_refusal_trace.py` 三探针；先写红：`test_cancel_token_overlapping_done`
- 冲突：CW-G5 触碰所有 cw worker done/error 槽——回归面大，必须整体一段做。

**C26 阶段路由 UI（A 方案）**（OA｜1d｜前置：C01；**B8d 之前**）
- 文件：`app/ui/bridge.py`(新独立 controller：ModelPolicyController)+设置面板新节（四阶段组下拉）；`app/model_strategy.py`(+quality_mix/budget_run 两卡)；新增测试：预设 JSON `{prose:{slot:"x"}}` 经 UI 写出与手写等价且 `stage_slot()` 解析一致；A14 回归（零静默换型）
- 验收：`pytest -k "strategy or slot" -q`；`tests/probe_qml_compile.py`。

**C27 Ollama 体检**（OD10｜1.5d｜前置：无）
- 文件：`app/llm/client.py`(/api/tags+/v1/models 双探测)、`app/llm/providers.py`(分诊文案)；mock 404/连接拒绝各一条文案断言。

**C28 skill 包 S 件**（SKILL-S｜1.5d｜前置：C01）
- 金标夹具冒烟 0.5+发布仓样例 0.5+发版联动 0.5（触点已回填：附录 C §1 建仓清单）；M/L 件 3d 另排。

**C29 自动备份**（BACKUP｜1.5d｜前置：C01）
- 文件：core 新模块 `app/core/auto_backup.py`（关项目/关应用 zip，`bridge.shutdown:2169`/`_maybe_auto_backup:5389` 雏形接线）；新增单测（临时项目→zip 产物+保留 N 份）。

**C10b 拆环1 project↔wb（B2b）**（0.5d｜前置：C01；**C30(B5a) 的前置**）
- 文件：`app/project.py:424-448`（worldbook_text/anchors 迁出）、`app/wb.py:480,691,728`（三处延迟 import 升模块级）+core 5 消费方改 import
- 验收：`./.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider`；`./.venv/Scripts/python.exe scripts/dep_graph.py`（SCC 期望 3→2）
- 回滚：单 commit revert。

**C30 存储门面下沉（三段插队）**（B5a/b/c｜4d｜前置：C10b）
- 验收（每子批）：`pytest tests/unit -q` 全量 + `dep_graph.py` 期望 37→25→20→13(全良性)；发版前加跑 `tests/probe_packaged.py --exe`；每子批独立 revert；与功能批完全并行安全（shim）。

**C31 bridge 切分（五 PR 插队）**（B8a-e｜6d｜前置：C01；b 待 C19-21 落地、d 待 C26、e 待 C25）
- a：`bridge.py:33-926` 12 类+纯函数平移 `app/ui/workers.py`（0.5d）
- b：Updates 域→`bridge_updates.py`（1d，专项 `probe_update_ui.py`）
- c：Io 域→`bridge_io.py`（1d）
- d：Settings/Connections→`bridge_settings.py`（1.5d，顺带消 ui→llm 直连）
- e：共写族→`bridge_cw.py` CwMixin（2d，Signal 已在主类声明区）
- 验收（每个相同）：`pytest tests/unit -q` 全量 + `probe_qml_compile.py` + `dep_graph.py`（bridge 出度下降、无 ui->core 新违规）；QML 面=零变化承诺
- 回滚：Qt 父子关系/QThread 归属随类平移不重排；单 PR revert。

### Wave 3

**C32 H-4 主体**（H4｜2-3d｜前置：C02；施工设计待补——缺口 G2）

**C33 T1 爽点账本（拆两段）**（卡3｜4.5d｜前置：**C11**；cw 字段段前置 C08）
- 段1（2d，B3 后即可）：`app/core/satisfaction.py`(+账本读写/rhythm_findings)+`app/config.py`(satisfaction_ledger 新键)+`app/core/l0_checks.py`(+挂 review_l0_block)+`tests/unit/test_satisfaction_ledger.py`
- 段2（2.5d）：双通道回写接线（细纲批 1159 解析后+`bridge.py:4460` _on_cw_batch_done+审校 B_PAYOFF 回写+`_mc_finalize` 落账）+cw 细纲字段扩展（`prompts/co_writing.py:259-293` 增节拍/钩子/字数三行）
- 验收：`test_rhythm_no_beat_run_over_two`（跨批边界恰 1 条 fail候选）；`test_closure_rule_uses_closed_not_false`；`test_ledger_off_byte_identical`；**显式更新 `test_satisfaction_engine.py:191-199` 钉值并跑绿**；`probe_prompt_baseline.py`

**C34 T2 钩子账本（拆两段）**（卡4｜4d｜前置：**C08**）
- 段1（2d）：新增 `app/prompts/hook_vocab.py`（7 型+判据+HOOK_ROUTE）+`planning.py:206,239` 字段升级+解析落账+`tests/unit/test_hook_ledger.py`（封闭性/弱钩连排/未应答 fail候选/低压子集）
- 段2（2d）：F 维 rubric 钩型判据（`review.py:169-175`）+账本回写（FINAL_REVIEW 解析处）+supervisor 对账域（`co_writing.py:353-397` 增「上章钩子回应核对」节）
- 验收：**W0c 钉测 `test_cw_prose_check.py:95-101` 显式改钉不静默绕开**；`pytest -k "hook" -q`；两档 prompt 同验。

**C35 G4+G5 看门狗与告警**（卡8-G4/G5｜3.5d｜前置：C02）
- `orchestrator.py:488-496`(+G4)、`app/usage.py:157-194`(+规则)、`app/core/state.py:366`(anomalies 键)+`volume_session.record_event` 复用；新增 `tests/unit/test_watchdog_missing_tracking.py`
- 验收：模拟 stop 杀在记账窗口 → 下章开写前看门狗触发；回放 T3 v1 台账命中 ch41-44 且 ch1-40 零误报。

**C36 G6 记账不可中断区**（卡8-G6｜1.5d｜前置：C02+**C11**；OC 硬前置）
- `stages.py:2233-2248`（write_file 后 in_epilogue；checkpoint 2236/2248 收口进 try；orchestrator pending_stop 章界统一停）；新增 `tests/unit/test_epilogue_no_stop.py`（8 章干跑 history/台账四相位齐全）

**C37 G7 检测口径**（卡8-G7｜1d｜前置：C02）
- `app/core/gates.py:131-160`（上限侧报告+短章 <floor×0.5 禁静默定稿+阻断数千字归一）；`pytest -k "precheck or word" -q`。

**C38 批量挂机 C（拆三段）**（OC｜6-8d｜前置：C36+C18(G3)+C35(G5 强)；H4 先行）
- 段1：`app/core/batch_run.py` 队列对象（N 章/字数二选一，orch 信号驱动根除文件轮询）；段2：三层熔断接线（G1/G3/bench_queue 3 败/G5+预算×1.5）；段3：挂机面板+offpeak_run 组合+`tests/long_run.py` 转正收编（成本栈四旗标收编）
- 验收：假 client 干跑 N=8 四相位齐全；连续 3 章 REJECT→paused 带区间；10 倍稿只烧 1 笔；¥0.5 预算超线停在章界+晨报。

**C39 成本面板 B 方案**（OB-cost｜2.5d｜前置：C35(G5)）
- `app/usage.py`(book-scope 聚合)+独立 controller+章列成本标注（`state.py:575` history 行）；验收：回放 T3 v1 台账 1705 行 → 命中率与记分卡一致；断网显示「盲区」非 0；章列成本与台账对账 ±1 分。

**C40 文档第二层**（DOC-4/8/9/10｜7.5d｜前置：C03/C13）
- DOC-4 首屏重构(2d)→DOC-8 证据链(1.5d)→DOC-9 手册 v2(2.5d)→DOC-10 随包 HTML+F1+About(1.5d)；验收：`check_docs.py` 检查 2/4 绿（≥500 行+面板覆盖）；打包态 selftest 断言 `help/*.html` 存在且版本一致。

**C41 onboarding M 批**（OB-M1-M4｜6-8d｜前置：C06/C07/C08；L1 另排 5d）
- M1 软开局(2-3d，消费 `_slot_readiness` 与档位一致 toast)→M3 就绪横幅(1.5d)→M4 静态示例书(1.5d，`app/ui/demo_pack.py` 扩展+演示守卫复用)→M2 内嵌表单(1.5d，视 M3 验收)；验收照 w3_onboarding §5 判据 5-8（10 分钟真机走查归发布窗口）。

**C16b deslop 规则 28→45（卡6M）**（3-4d｜前置：C16；B5b 后搬（先落后搬））
- 文件：`app/deslop.py`（规则扩容+maskQuoted 重写 `_in_dialogue:118`+书级白名单+review 二轴）、`app/prompts/writing.py:214-240`（DESLOP_REWRITE_PROMPT 切片三消费点**同步纪律**，先过 B2c 拆环）、`app/core/shared_prefix.py`(D9 复用)；新增 `tests/unit/test_deslop_rules_expansion.py`
- 验收：合成毒文本检出 ≥90% + 真人样例 blocking 误报=0（w3_deslop §5 M 档判据）；lieflat 切片三消费点逐字同步断言；`pytest -k "deslop" -q`
- 冲突：oh-story 阈值不可直接搬，需语料误报校准纪律（附录 B 卡6）；B2c 拆环先行动。

**C42 卡9-P1/P3 事实账本与四查**（｜5-6d｜前置：C25-CW-G6；Wave 3 末-4）
- P1：新增 `app/core/fact_ledger.py`（原型 `_scratch/superiter/proto/p1_quote_anchor.py` 移植）+`_mc_finalize`/`_run_backflow:744` 双挂点+`追踪/事实账本.jsonl`；P3：新增 `app/core/maintenance.py`+待确认卡片（独立 `cw["maintenance"]` 通道，不进 report 单槽）
- 验收：三类幻觉样本全拦+噪声 100% 归一化救回；新实体出待确认项而非自动写库。

### Wave 4（占位）
**C43 卡5-T5 桥段码账本**（4-6d｜前置：C33+版权裁决②）；**C44 爽点盲评 A/B**（花钱，待裁决①，协议随 w5_satisfaction）；**C45 T3 v3 预注册长跑**（护栏全开：C17/C18/C24/C36 就绪）；**C46 1.0 判据收口**（12 条达成 10 条）。

---

## 六、缺口清单（规划了但施工细节不足）

| # | 项 | 缺什么 | 建议 |
|---|---|---|---|
| G1 | QW-A7 自动开章 | 报告给的钩子 `_on_cw_stage` 在 HEAD **不存在**（grep 无此方法；实际经 `cwStageChanged` Property/`_get_cw_stage_key` 1224 派发） | C07 施工首小时定位真实阶段切换点（候选：`_on_cw_sum_done:5123` advance 后或 CoWriting.advance 调用点），回填本卡 |
| G2 | H4 主体 | 蓝图只有定位（跨线程 load→改→save 丢更新）与排期，**无触点/无验收/无 diff** | C32 开工前补施工级设计（嫌疑面：`state.py` save_state 全量回写 + worker 线程并发；验收=丢更新窗口注入测试） |
| G3 | 自动备份 BACKUP | 无报告给出触点与验收（仅 w4 §四一句「逻辑放 core 新模块」） | 已按 shutdown/_maybe_auto_backup 雏形拟 C29 最小卡，开工前补 zip 保留策略与排除规则 |
| G4 | 卡9-P1/P3 的 Wave 归属 | plan_b 排在卡10-CW-G6 之后，但蓝图 Wave 0-3 未明示；依赖链使它落在 Wave 3 末-4 | 已排 C42 并标注；若 Wave 3 装不下顺延 Wave 4 与卡5 同窗 |
| G5 | SKILL 三件 | ~~触点未核~~ **已回填**：附录 C §1 建仓清单（C28 已引用） | 蓝图关键路径 4-5 人日 |
| G6 | PROMO 促销片防腐 | ~~无文件级清单~~ **已回填**：附录 C §2（SceneProduct.tsx:130/SceneCTA.tsx:121/components.tsx:173 三处 0.19.9 实测） | C18 窗口执行 |
| G7 | U-C 清理函数签名 | 「三份 setup→剩两份」单测需要版本感知，update_install.py 现无版本参数，设计未给签名 | C09 内补：清理函数带 current_version 入参，单测 monkeypatch |
| G8 | 卡2 批次 L0 与 partial-batch 交互 | 注入点 stages.py:1101 返回前与现有 `test_outline_partial_batch` 的 fail-open 交互未写明 | C14 单测覆盖「部分批次+超期伏笔」组合用例 |
| G9 | I18N A 路触点 | ~~声明行落点未定义~~ **已回填**：C12（README 顶部一行+check_docs 追加检查项） | 验收=check_docs 新检查项绿 |
| G10 | OB-M2/M3/M4 | 触点只有 QML 文件名级，无 diff 级；M4 需读 `app/ui/demo_pack.py`（127 行）定扩展点 | C41 开工前各补 0.5h 读码回填 |
| G11 | 卡8-G5 阈值细节 | `0.8×max_tokens` 对不报 max_tokens 的渠道退化为不判——降级口径未写；anomalies 键 UI 横幅消费方（Main.qml binding）无设计 | C35 内补（不判时记 debug 不记 error） |
| G12 | OC 与 `writing.offpeak_run` 组合 | config.py:109 offpeak_run 升级为「离峰自动开跑批次」的 UI/配置面未设计 | C38 段3 内补 |

---

## 附：口径与纪律
- deslop 规则数统一「28 个 rule id（10 blocking+12 密度+6 结构）」；盲评历史以 tiebreak.json（-0.33）为准；更新通道「4 在线+2 本地兜底」；版本锚 0.20.1（HEAD 2de3e9d），latest.json 0.20.0 是漂移（C03 修）。
- 本文件为只读施工说明，未改主仓库任何文件；核实脚本 `verify_touchpoints.py`/`verify_touchpoints2.py` 可复跑（.venv，纯只读）。
