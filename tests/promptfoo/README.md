# tests/promptfoo —— E4.2 promptfoo 矩阵台（O11，可选工具链）

把「细纲 prompt 变体 × 模型档位 × 变量」的矩阵实验 YAML 化。对齐：

- `docs/成本测试方案_v2.md` **§E4.2**（本目录的实验定义）与 **§E1.2**（显式输出长度预算，本模板对应的正式实验）
- `docs/成本优化深度调研报告_v2.md` **§2.6**（promptfoo 能力盘点、内置价目是促销旧价的告警、effort 扫描的变量隔离方法论）

## 文件清单

| 文件 | 作用 |
|---|---|
| `promptfooconfig.yaml` | 矩阵配置：2 prompts × 2 providers × 2×2 vars，含 cost / latency / is-json / llm-rubric 四类断言与 defaultTest 兜底 |
| `prompts/outline_budget_v1.txt` | 细纲 prompt 基线变体（无预算段） |
| `prompts/outline_budget_v2.txt` | 预算变体 = v1 + 「输出预算与结构」硬约束段（措辞仿 `app/core/stages.py` 的 `_dyn_directives`），**除该段外与 v1 逐字节相同** |

两个变体是真实细纲任务（`app/prompts/planning.py` 的 `CHAPTER_OUTLINE_PROMPT`）的**单章简化版**：为让 `is-json` 断言可判，输出格式约定为严格 JSON；占位符 `{{genre}}`、`{{chapter_words}}`、`{{length_budget}}` 由 tests.vars 注入。

## 安装与运行

本机未安装 promptfoo 时（Node.js ≥ 18，DeepSeek key 已在凭据管理器者无需再设 env，否则先导出）：

```bash
npm install -g promptfoo        # 或不装全局，直接用 npx
export DEEPSEEK_API_KEY=sk-...  # Windows: set DEEPSEEK_API_KEY=sk-...
```

在**本目录**（`tests/promptfoo/`）下运行：

```bash
npx promptfoo eval --no-cache   # 真实成本口径：必须带 --no-cache（理由见下）
npx promptfoo eval -o out.json  # 可选：导出结果（支持 .json/.csv）
npx promptfoo view              # 本地起 Web 界面查看矩阵结果
```

### 为什么 `--no-cache` 才是真成本

`promptfoo eval` 默认启用本地响应缓存（`~/.promptfoo/cache`）：同一 (prompt, provider, vars) 组合重复 eval 时直接回填上次结果，**不再产生新调用**。缓存命中会使 `cost` 与 `latency` 断言度量到的是旧调用，成本对比失效。所以：

- **测真实成本 / 跑正式对比**：必须 `--no-cache`（E4.2 原文注意点）；
- **prompt 措辞迭代期**：可以去掉 `--no-cache`，故意吃缓存省重复调用费。

## 价格覆盖：为什么必须改、改成了什么

**promptfoo 内置的 DeepSeek 价目是促销旧价（$0.0028/$0.14/$0.28）**（来源：调研报告 §2.6 与成本测试方案 P6 纪律），直接用会把成本算错数倍，因此本配置在 provider 级 `config` 覆盖为**成本台账口径**：

| 模型 | 输入 cache-hit | 输入 miss | 输出 | config 字段取值 |
|---|---|---|---|---|
| deepseek-v4-flash | $0.007/M | $0.22/M | $0.66/M | `cost: 0.000000007`、`costOutputToken: 0.00000066` |
| deepseek-v4-pro | $0.022/M | $0.66/M | $1.98/M | `cost: 0.00000066`、`costOutputToken: 0.00000198` |

- 单价单位是 **$/token**（每百万价 ÷ 1e6），人民币汇率 **¥ = $ × 7.2** 仅在此注明（台账 `docs/成本台账.md` 头注与 `scripts/cost_bench.py` 的 `PRICE`/`USD_CNY` 常量同源）。
- **来源与日期**：DeepSeek 官方定价页，2026-09-06 核对，**off-peak（错峰）口径**；白天时段价格更高。
- **hit/miss 近似说明**：promptfoo 只有「prompt 单价（`cost` 字段）+ 输出单价（`costOutputToken`）」两个槽，无法同时表达 hit 与 miss 两个输入价。本模板 flash 的 `cost` 槽填 **cache-hit 价 $0.007/M** 做近似；若要把 `cost` 断言当**严格上限**（`--no-cache` 只关本地缓存，服务端前缀缓存命中与否不影响费用上限判断），把 flash 的 `cost` 改为 `0.00000022`（miss 价）更保守。pro 直接填 miss 价 $0.66/M（其 hit 价 $0.022 无槽可填，已在 YAML 注释说明）。
- **P6 纪律**：价格会变（行业在涨价），**每次实验当天重新核对官方页**，不要信任何过期数字（包括本 README）。

## 断言组合（E4.2 四类演示）

- `cost`：单次调用美元上限。defaultTest 兜底 $0.2/次，最后一行演示按行收紧到 $0.1。这是**单跳上限**，不是「每章成本」。
- `latency`：毫秒上限。兜底 10 分钟（off-peak 历史数据中细纲相位有 431s 量级，见 `docs/成本优化深度调研报告_v2.md` 的 v1 验收还原数据），演示行收紧到 5 分钟。
- `is-json`：输出可解析为 JSON（本模板的细纲约定输出严格 JSON）。
- `llm-rubric`：模型评分。**评分器兜底用 flash**（`defaultTest.options.provider`），并演示了自定义 `rubricPrompt`（模板串须含 `{{rubric}}` 与 `{{output}}`，约定最后一行输出 pass/score/reason JSON）与行级 `provider` 覆盖写法——评分也是一次真实调用，用 flash 把评分成本压到最低。

注意：thinking 模型的输出前部可能带推理段；本模板的评分 prompt 已约定「最后一行只输出 JSON」以降低解析失败率。若实际运行中 `is-json`/`llm-rubric` 频繁误判，优先收紧输出格式约定，而不是放宽断言。

## 怎么扩成完整的 E1.2 实验

本模板 = 2 变体 × 2 模型 × 4 变量行的**骨架**。扩到 E1.2「outline-budget」正式实验：

1. **换真 prompt**：把 `prompts/` 下两个文件替换为真实细纲模板（保持 JSON 或约定可解析格式），两变体仍须**除预算段外逐字节相同**——变量隔离纪律（调研报告 §2.6 effort 扫描方法论：各档 byte-identical 除目标变量外、同模型、每档跑完再换下一档以保缓存可比）。
2. **vars 扫预算档位**：`length_budget` 取多档（如 600 / 900 / 1400 / 不设限=v1 对照），每档一组 tests 行；`chapter_words`、`genre` 按种子书口径固定。
3. **断言**：promptfoo 内用 cost/latency/is-json/llm-rubric 做硬指标初筛与废跑过滤；E1.2 的正式质量验收（outline→正文 verdict 全过 + 盲评不掉）**不在 promptfoo 内做**，需要全流水线——走 `scripts/cost_bench.py`。
4. **记录**：结论照 E4.2/§7 模板落行（变体、相位级输出 tok、裁决），metrics 存 `tests_output/bench/<variant>.metrics.json`，价格口径在实验有效性注记里写明 off-peak 与核价日期。

## 什么时候不该用 promptfoo，而该用 scripts/cost_bench.py

| 用 promptfoo | 用 cost_bench.py |
|---|---|
| 单 prompt 变体矩阵：预算档位、措辞 A/B、输出格式（JSON vs 文本） | 全流程流水线实验：缓存命中率（E0.2/E2.x）、章会话栈、双层前缀、闸门/级联（E3.x）、每章综合成本（E0.1 基线） |
| 需要 prompts × providers × vars 叉乘 + 硬断言过滤 | 需要真实相位序列、usage.jsonl 全量聚合、metrics.json 台账对接 |
| 单跳调用，成本量级几毛钱 | 多章微循环，成本按实验预算控制（R1 ~¥3.6 等） |

promptfoo 只发**单跳调用**，测不了流水线行为（相位级联、前缀缓存、闸门重试），也算不出「每章成本」。E4.2 原文取舍：「若 cost_bench.py 已够用则只抄它的 `cost` 断言思想，不强迁」——本目录定位是**配置模板先行**，是否启用由 E1.1/E1.2 实验结果决定。

## 成本预估与状态

一轮全矩阵 = 2 prompts × 2 providers × 4 行 = **16 次生成调用** + 2 行 llm-rubric 的 **8 次评分调用**（flash 评分），简化 prompt 下 off-peak 合计 **远低于 ¥1**（量级估计，以实际 usage 为准）。

**状态**：本机未安装 promptfoo，配置未实际 eval 过；YAML 语法已用 PyYAML `yaml.safe_load` 校验通过，字段名以 promptfoo 官方文档为准（https://www.promptfoo.dev/docs/configuration/guide/ ），首次运行若提示字段变更按官方文档微调。两个 prompt 变体的字节隔离已用 `diff` 验证（仅末尾预算段差异）。
