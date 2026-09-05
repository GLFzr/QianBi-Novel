# 优化方案：DSH 缓存深度研究 + 运行架构调整（v0.19 规划）

> 基线：v0.18.4 发布当日验收跑（2026-09-05 18:42–21:25，deepseek-v4-flash，57 笔调用全量埋点）。
> 本方案回答用户三问：① DSH 缓存到底怎么做到 99.9%，我们还差什么；② 需不需要调整运行结构；
> ③ 调整如何**保证**成本下降、体验提升、质量不降。

---

## 一、验收跑逐笔数据还原（缺口定因）

57 笔调用的逐条 hit/miss（off-peak 时段）聚合：

| phase | 笔数 | 输入 hit% | 均延迟 | 均输出 tok |
|---|---|---|---|---|
| review | 19 | 64.1% | 170s | 17.1k |
| prose | 6 | 40.0% | 265s | 24.7k |
| deslop | 6 | 54.9% | 15s | 2.6k |
| tracking | 6 | 58.1% | 39s | 6.2k |
| **outline** | 4 | **0.0%** | 431s | **38.0k** |
| enrich | 3 | 42.5% | 26s | 3.1k |
| chapter_summary | 4 | 85.3% | 2s | 70 |
| trim | 1 | 62.2% | 116s | 16.0k |
| **review_fix** | 1 | **0.0%** | 263s | 32.6k |
| **volume_outline / core_setting** | 各1 | **0.0%** | 262-323s | 27.7-30.9k |
| global_summary | 4 | 96.8% | 3s | 287 |
| canon_audit | 1 | 99.8% | 192s | 5.8k |
| **合计** | 57 | **57.8%** | — | 799k |

### 定因（四条，全部实锤）

1. **【真 bug】章级共享段从未进过任何 prompt。** 7 处 format 调用传了 `chapter_header=chapter_header(proj, num)`
   （stages.py 839/869/893/950/1173/1185/1812 行），但 **0 个模板含 `{chapter_header}` 占位符**
   （含 PROSE/ENRICH/TRIM/DESLOP/CH_SUMMARY/G_SUMMARY/FINAL_REVIEW/TRACKING 全部）。
   `.format()` 静默丢弃多余参数 → 第二层前缀"计算了、缓存了（进程内 LRU）、但从没上过线"。
   实测佐证：全 run 稳定共享前缀 = 13,440–13,696 tok（恰为 project_header 的 block 取整），章内章间完全一致。

2. **outline 系全家桶没接 project_header，且模板首行即逐章变量。** `CHAPTER_OUTLINE_PROMPT` 首行
   "为第 {chapter_num} 章设计细纲"（planning.py:145），从第 20 个字符起字节即断 → 4 笔 0%，
   且 outline 是全流水线最贵的调用（431s、38k 输出/笔）。

3. **审校投票并发烧掉两份全价 miss。** 三票同一 prompt（仅温度不同），前两票并行下发 → 缓存写竞态，
   两票都只命中 project_header（实测均 13.5k/27.4k=49.9%），第三票才 99.6%+。
   早停几乎未触发（6 章 19 票 ≈ 3.2 票/章；另：**v4 thinking 模式忽略 temperature**，
   投票差异全部来自思考随机性，调温无用）。

4. **DeepSeek v4 缓存注册是异步的（秒级~分钟级落盘）。** enrich 在 prose 结束**同秒**启动 → 0%；
   deslop 30s 后启动 → 只捡到 7,680 tok（一半）；6 分钟后的 tracking → 全额 13,440。
   长调用紧跟着的快速调用会白miss一轮。

### 成本结构已经变了（v4 价格，off-peak 半价档）

| 项 | v4-flash off-peak | 本次跑 | 占比 |
|---|---|---|---|
| 输入 miss 523k | $0.22/M | $0.115 | 18% |
| 输入 hit 717k | $0.007/M | $0.005 | 1% |
| **输出 799k** | **$0.66/M** | **$0.527** | **81%** |

**结论：v3 时代"输入贵、拼缓存"的局面已反转，输出 token（thinking + 生成）占账单 81%。**
缓存优化仍要做（miss 单价是 hit 的 31 倍），但只修输入最多省 18%；大头在输出侧。
（peak 档全部翻倍：UTC 周一至五 01:00–04:00 / 06:00–10:00 = 北京 09:00–12:00 / 14:00–18:00。）

---

## 二、DSH 与官方机制拆解（本轮研究结论）

官方 KV cache 指南（v4，SWA 架构后已**改机制**）+ harness 社区正反案例：

- **缓存自动开启、免代码**；每请求在「用户输入末尾」「模型输出末尾」以及「长输入的固定 token 间隔」
  处切出**独立的缓存前缀单元（unit）**；命中要求**完整匹配某个 unit**（A+C 不能命中 A+B 单元）。
- **公共前缀检测**：两次请求共享的前缀 A 会被自动固化为 unit，后续 A+D 可命中 →
  即使我们每章只发一次性调用，只要前缀字节稳定，**第 2~3 次起就会命中**。
- 缓存**尽力而为**：构建需数秒、注册异步（我们的 enrich 0% 即此）、闲置数小时~数天清除。
- harness 99.93% 的本质（社区 98.09% 实测同构）：**系统提示词不可变 + 工具表定序 + 对话只追加不改动**
  ——它是"单会话迭代"工作负载，前缀天然稳定；0% 反例（#3304）全是前缀里混入动态内容/顺序漂移。
- 我们与 harness 的差异：流水线是"多阶段×多章"工作负载，每阶段 prompt 不同、每章上下文不同
  ——**不可能照搬 99.93%，但能把"章内 8 次调用"变成 harness 式追加结构**（见第四节架构项）。
- thinking 参数：`thinking.type=enabled/disabled`；`reasoning_effort` 实际只有 **low / high / max**
  三档（medium/high/xhigh 都映射到 high）；**默认开启且默认 high** —— 这就是 outline 38k、
  review 17k 输出的直接原因。thinking 模式下 temperature/top_p 等采样参数**静默无效**。

---

## 三、第一包：修 bug + 顺手收益（无结构变更，先行发布）

预计整体命中率 57.8% → **72~80%**，输入成本 -35~45%；不触碰任何生成语义。

1. **补 `{chapter_header}` 占位符**（bug 修复）：ENRICH/TRIM/DESLOP/CH_SUMMARY/G_SUMMARY/TRACKING
   六个模板在 `{project_header}` 后紧跟 `{chapter_header}`，并**删除这些模板中原有的重复段**
   （outline_brief/character_state/foreshadow_table 等散装注入——chapter_header 已含
   细纲+角色状态+时间线+伏笔+近2章摘要的完整版）。PROSE 与 FINAL_REVIEW 同样把内嵌的
   同源段落替换为 `{chapter_header}` 引用，动态尾只保留真正逐次变化的
   （wb_block/craft_block/user_guidance/previous_excerpt/正文本身）。
   - chapter_header 组成扩充：纳入 上一章结尾 + 上一章开头样本（prose 的衔接与文风锚定），
     使 prose 模板动态尾再瘦身；这些文件在章循环开头即已定稿，章内字节稳定成立。
   - 双层前缀顺序纪律写入编码规范：`project_header` → `chapter_header` → 阶段静态指令 → 动态内容，
     任何新阶段不得在两层前缀之间插动态值。
2. **outline 系接前缀**：CHAPTER_OUTLINE / VOLUME_OUTLINE / CORE_SETTING 三个模板改为
   `[project_header][细纲方法论静态块][动态尾部]`，动态值（章号/近章摘要/前章结尾/用户指令）全部后置。
   同时 outline 默认批量 2 章/调用（现支持批量，实测跑成了单章×4）：outline 调用次数减半、
   第二次起命中 project_header。
3. **审校投票重排**：vote1 单发（暖缓存：其完整 prompt 落盘）→ votes 2+3 并发。
   墙钟与现状两阶段制相同；votes2+3 命中 vote1 的全量前缀（预计 49.9%→~95%）。
   早停判据移除（temp 无效化后三票几乎必不同，早停名存实亡；省下的判断换确定性的缓存收益）。
4. **review_fix 接双层前缀**（0% → 章内高命中）：复用统一模板骨架。
5. **微循环顺序微调**（可选）：prose 后第一个快速调用从 enrich 挪后一位，把异步注册窗口
   （实测 30~60s）留给长调用 review；enrich/deslop 顺延。收益小（~$0.005/章）但零成本。

## 四、第二包：运行结构调整——「章会话消息栈」（90% 的兑现路径）

**这是对"需不需要调整结构"的回答：需要，且值得。** 但它不改阶段语义、不改质量闸门，
只是把"每阶段一条独立 prompt"改为"每章一个会话，阶段是会话里的追加轮次"：

```
messages = [
  system: project_header + chapter_header        ← 全章 8+ 次调用逐字节同一份（~19k tok）
  user:    正文写作指令（阶段静态 + 动态尾）
  assistant: 第 N 章正文                           ← 只传输/计费一次
  user:    六维终审指令                            ← 追加轮
  assistant: 审校报告
  user:    tracking/摘要/canon_audit 指令 …
]
```

- 收益机制：第 2 轮起，此前所有轮次整体命中缓存——**正文文本、审校报告这些"必然逐章不同的
  大块动态"从 miss 变 hit**。这正是 harness 99.93% 的结构在本项目工作负载下的等价物。
- 预估：章内第 1 轮 miss ~34k，其后每轮仅 miss 增量指令 2~4k、hit 34~38k
  → **章会话内命中率 88~93%，全流水线混合 82~88%**（一次性调用 outline 已被第一包修好）。
- 附带红利：tracking/audit/deslop 本来就要"读正文"，多轮结构下它们天然看到全文，
  `prose[:6000]` 截断（review）与 `[:1500]` 状态截断可放宽或取消——**质量侧反而受益**。
- 风险与对策：
  - 前轮结论泄漏（deslop 看到审校报告被带偏）→ 各追加轮开头加一行作用域声明
    （"仅依据 system 事实与本章正文执行本步，忽略前轮评审性发言"）；质量对照验证专项覆盖。
  - 输入总量膨胀（assistant 轮计入输入）→ hit 价是 miss 的 1/31（off-peak），净赚；
    且 thinking 轮的 reasoning_content 不落上下文（官方文档），不膨胀。
  - 客户端改造：`LLMClient._build_payload` 已接受 messages 数组，补一个 `chat_turn(session, ...)`
    会话入口 + stages 调用点逐阶段迁移（一次迁一个阶段，A/B 可回退）。
- 质量不降的保证：第四节验证流程先跑第一包（纯 bug 修复，理论上零语义变化），再跑第二包
  （逐阶段迁移、每阶段独立 A/B），任何一阶段分数跌破地板即停用该阶段迁移、回退单轮。

## 五、第三包：输出成本（账单 81% 的大头）

6. **thinking 分档调优**（对照验证后定档）：outline 与 review 从默认 high 降到 low
   （细纲排期与规则执行型任务，low 档预期够用；prose 保持 high 不动）。
   预期输出 -25~35% ≈ 总成本 -20~28%。canon_audit 维持 high。
7. **离峰挂机**（新特性）：v4 off-peak 全线半价（北京时间：工作日 0:00-9:00 / 12:00-14:00 /
   18:00-24:00 + 全周末）。设置面板加"离峰批量写作"开关：排队的章在离峰窗口自动续跑。
   用户挂机一晚 = 直接 -50%。
8. **usage 面板补 reasoning 口径**：completion 里拆 reasoning_tokens（响应已有 reasoning_content），
   让"输出花在哪"可见，为后续调档提供数据。

## 六、质量对照验证设计（每个包的发布闸门）

- **基线**：v0.18.4 验收跑的 6 章文本 + 评分 + 审校六维数据（已留档）。
- **方式**：同一本书继续下一 6 章（能力轮同款评估子代理流程：7 项独立审计 + 总分 + 地板线）。
- **通过标准**：总分 ≥ 基线−0.5；单章地板 ≥ 7.5；审校 fail 维度不升；
  命中率达到该包预估下限（第一包 ≥70%，第二包 ≥80%）。
- **顺序**：第一包 → 验证 → 发布小版本；第二包逐阶段迁移 → 每阶段验证；第三包 thinking 降档 → 盲评。
- 说明：原"90% 命中率"目标在 v4 单轮结构下的物理上限 ≈ 80%（动态尾必然逐章不同）；
  章会话化后 82~88%，其余靠 unit 机制的自然收敛。**成本目标（较 v0.18.4 -50% 以上）由
  第一包 + 第三包共同兑现，不依赖把命中率硬顶到 90%。**

## 七、执行顺序与工作量

| 步骤 | 内容 | 规模 |
|---|---|---|
| 1 | 第一包 1-5（模板占位符 + outline 前缀 + 投票重排 + 顺序微调） | 1 个子代理，半天 |
| 2 | 6 章对照验证跑 + 评估 | 半天（含等待） |
| 3 | 发布 v0.18.5（bug 修复包） | 复用发布脚本 |
| 4 | 第二包：client 会话入口 + 逐阶段迁移 | 1-2 个子代理，1-2 天 |
| 5 | 第三包：thinking 调档 + 离峰挂机 + reasoning 口径 | 1 个子代理，半天 |
| 6 | 全量验收（质量 + 命中率 + 账单三口径）→ v0.19.0 | 半天 |

---

### 附：本轮数据与结论的可复核性

- 逐笔数据：`~/.qianbi_novel/usage/usage.jsonl`（09-05 57 笔，hit/miss/phase 列）。
- chapter_header 缺口复核：`python -c "import app.prompts as p; print('{chapter_header}' in p.PROSE_WRITING_PROMPT)"`
  → 全部模板 False；对照 stages.py 7 处传参。
- 价格与机制：api-docs.deepseek.com `/guides/kv_cache`、`/quick_start/pricing`、`/guides/thinking_mode`
  （2026-09-05 抓取，v4-flash：hit $0.007-0.014 / miss $0.22-0.44 / out $0.66-1.32 每百万，
  peak=UTC 周一至五 01:00-04:00 与 06:00-10:00，其余 off-peak 半价）。
