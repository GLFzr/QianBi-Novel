# OpenCode Go 免费模型使用指南（space-bunny-free / longcat-2.5-preview-free）

- **实测定稿**：2026-10-03（全部结论来自当日真发探针，标注于各节；探针脚本思想见 `tests/ab_arms.py` / `tests/quality_suite.py`）
- **使用限制（用户指派，硬约束）**：OpenCode Go 通道**只允许** `space-bunny-free` 与 `longcat-2.5-preview-free` 两个免费模型；`/v1/models` 列表里的其余模型全部为付费，**一个请求都不许发**。

---

## 一、连接参数

| 项 | 值 |
|---|---|
| base_url | `https://opencode.ai/zen/go/v1` |
| 免费模型 ID | `space-bunny-free`、`longcat-2.5-preview-free`（以 `GET /v1/models` 实时清单为准） |
| 认证 | `Authorization: Bearer <key>`；key 只存 `G:\ai\launcher-webui\state\api.key` 同级的本地文件或环境变量（`QIANBI_OC_KEY`），**不入 git** |
| **会话头（必填）** | `x-opencode-session: <稳定会话ID>`——缺失直接 `400 MissingSessionID`（10-03 实测）。值用稳定串（如 `qianbi-<用途>-<随机8位>`），网关用它做路由与 prompt 缓存优化 |

千笔客户端（`app/llm/client.py` `_headers()`）已自动处理：连接 `base_url` 含 `opencode` 即附带 `x-session-id` 与 `x-opencode-session`（值取连接的 `user_id`，缺省 `qianbi-novel`）。**同一会话域保持同 ID**——换 ID 会打散网关侧 prompt 缓存。

## 二、双模型画像（10-03 实测）

| 维度 | space-bunny-free | longcat-2.5-preview-free |
|---|---|---|
| 思考负担 | **重**（思考 tokens 从 max_tokens 里扣） | 无（直接出正文） |
| max_tokens 要求 | **探针（短 prompt）≥16384 即可；重管线 prompt（入 ≥10k tok + effort=high）实测 16384 仍被思考吃光→0 字（`finish=length`），需 32768**。千笔的空内容升级链（16384→32768，`_ESCALATE_CEILING`）可自愈，但代价是首轮整段浪费（实测第 8 章：358s 空 + 1603s 成功 = 单草稿 33 分钟）。**建议：管线场景直接把 max_tokens 设 32768**，或 prose 相位降 effort | 不敏感（1287/474 tok 均正常收尾） |
| `reasoning_effort` | `"high"` **生效**：思考 tok 稳定 230-340（无 0 样本）；`"xhigh"` 语法收下但思考反降（出现 0 样本，勿用）；`"x-high"` 直接 400 | 未观察到需求（缺省即可） |
| 长 prompt 非流式 | 2364 字 prompt→16384 预算：**42s / 927 字 / finish=stop** ✅；真管线（15k tok 入，effort=high）：首轮 empty→升级 32768 后 **1603s / 13,435 tok** ✅ | 同 prompt：**42s / 714 字 / stop** ✅ |
| 短 prompt | ~1-3s | ~1-3s |
| 已知怪癖 | 空内容时先查 max_tokens 是否被思考吃光（用法行 `usage.completion_tokens` 大而 content 空 = 思考超支） | 无 |

**千笔连接模板**（写入 隔离配置 或测试驱动；`reasoning_effort` 由 `_build_payload` 原样下发）：

```python
{
    "id": "oc-go", "name": "OpenCode Go 免费通道",
    "base_url": "https://opencode.ai/zen/go/v1",
    "api_key": os.environ["QIANBI_OC_KEY"],
    "model": "space-bunny-free",          # 或 longcat-2.5-preview-free
    "stream": False,                      # 两模型非流式均正常
    "max_tokens": 16384,                  # space-bunny 必须 ≥16k（思考预算）
    "timeout": 900,
    "reasoning_effort": "high",           # 仅 space-bunny 需要；longcat 可空
    "user_id": "qianbi-<用途>-<随机>",     # 派生稳定会话头
}
```

## 三、测试驱动接入

- **三臂 A/B**（`tests/ab_arms.py`）：设 `QIANBI_OC_KEY`（必填）+ `QIANBI_OC_MODEL`（可选，缺省 space-bunny-free）即自动切换到本通道；不设则回落 OpenRouter stealth。
- **长跑**（`tests/long_run.py`）：`QIANBI_TEST_BASE=https://opencode.ai/zen/go/v1` + `QIANBI_TEST_MODEL=space-bunny-free` + `QIANBI_TEST_STREAM=false`（C44 路径）；space-bunny 记得 `QIANBI_TEST_MAX_TOKENS≥16384`。
- **质量套件**（`tests/quality_suite.py`）：`QIANBI_OC_KEY` 未接入 `_client()`——评委仍走 stealth；如需切换在 `_client()` 的连接模板里加同款字段。

## 四、排障速查

| 症状 | 根因 | 处置 |
|---|---|---|
| `400 MissingSessionID` | 缺 `x-opencode-session` 头 | 千笔 `_headers()` 已自动带；裸 curl/httpx 必须手加 |
| `finish=length` 且 content 空 | 思考吃光 max_tokens（space-bunny） | 短 prompt：max_tokens ≥16384；**重管线 prompt（入 ≥10k tok）：直接 32768**（或 prose 相位降 effort）——16384 在重 prompt 下不够（10-04 实测） |
| 输出突然变短/变敷衍 | `reasoning_effort` 填了 `xhigh`/`low`（思考被抑制） | 用 `high` 或干脆不发该参数 |
| 内容疑似复读其他段 | 与模型无关——检查是否触发了扩写/去味环的旧路径 | 确认 `writing.enrich_para`/`deslop_cards` 开着（0.20.4 缺省开） |
| 付费模型误用风险 | `/v1/models` 列出 35+ 模型 | 只允许白名单两个 ID；驱动层勿把用户输入透传为 model |
| **`400 Upstream request failed: invalid request`（间歇）** | 上游对**携带成章正文**的请求（补尾/扩写/去味/记账/摘要）间歇拒绝——10-04 连续 6 章实测：同栈 prose/审校常过、改写类常拒，且逐章加重 | 千笔降级链已全量接住（补尾→降级建议 / 去味→保留原稿转待修 / 记账摘要→不阻断）；**400 按纪律不可重试**（确定性内容形状，重试无效）；高频期换 longcat-2.5-preview-free 或等窗口 |

## 五、实测记录（10-04，二测项目续写第 8-13 章全管线）

- space-bunny-free + 压缩@48k + 全 0.20.4 机制：**+6 章 / 11,067 字 / 866s（末轮 3 章）**；
- 机器指标：密度 0.49-5.06（第 11 章 5.06 为 400 降级章——扩写被拒后未达标），复现 0.041-0.062——**全部落在真人基线邻域**（基线 0.048）；
- 400 间歇拒绝 6+ 发，降级守卫全部接住（0 杀章——修正前的两轮各死 1 章）；
- 成本估算 ¥0.77/3 章（内部价目口径；通道实际免费）。

## 六、与千笔既有机制的相容性

- **C44 非流式开关**：两模型非流式均正常（42s 级长输出实测无 keep-alive 截断——OpenRouter stealth 的空白填充病在此通道未出现）；
- **净增益闸/卡片制/拍段预算**（0.20.4）：纯本地验收件，与通道无关；
- **预算宪法**：space-bunny 单发思考可达 10k+ tok，`gen_budget.max_single_tokens=32768` 够用；若再上调 max_tokens 需同步检查该轴；
- **对话台账/用量台账**：正常落账（usage 含 reasoning tokens，由 `completion_tokens_details.reasoning_tokens` 通道采集）。

---

## 七、2026-10-14 复测：space-bunny-free 已下线，免费清单变更

> 探针：`_scratch/oc_probe.py`（2 发最小请求）与 `_scratch/oc_model_profile.py`（同一段 600 字中文 prompt × 每模型 1-2 发）。
> key 只经环境变量 `QIANBI_OC_KEY` 注入，不入仓。

| 模型 | 状态 | 实测 |
|---|---|---|
| `space-bunny-free` | **已下线** | `GET /v1/models` 不再列出；调用回 `400 Upstream request failed: Model is unavailable`。本文第一~六节的画像是历史记录 |
| `longcat-2.5-preview-free` | ✅ 可用（**主力**） | 600 字请求 39-45s / `finish=stop` / 输出 1232-1420 tok（含 reasoning 620-899）；1 章 2000 字级全管线正常收尾 |
| `step-5-preview-free` | ⚠ 间歇可用（兜底） | mx=4096 → 25.9s / 1991 tok 正常；mx=16384 → `429 Endpoint is unavailable`（重试可过） |
| `cat-jam-free` | ❌ 不可用 | 两种预算均 `403 Endpoint is unavailable` |

**战役接入**：`tests/campaign_drive.py --spec _scratch/campaign/spec.json`（3 本 × 50 万字；主力 longcat、兜底 step-5；每轮独立子进程、崩溃隔离、断点续跑；模型 id 硬校验必须含 `free`）。
**参数取用**：`QIANBI_TEST_BASE=https://opencode.ai/zen/go/v1`、`QIANBI_TEST_MODEL=<free 模型>`、`QIANBI_TEST_STREAM=false`、`QIANBI_TEST_MAX_TOKENS=32768`、`QIANBI_TEST_TOTAL_WORDS=<本目标>`、`QIANBI_TEST_USER_ID=qianbi-campaign-<固定串>`（稳定会话头，网关侧 prompt 缓存不打散）。

**已知观测副作用（非通道问题）**：免费模型不在 `ledger_view` 价目表内 ⇒ 按最贵默认档（2.0/8.0 元每百万）估算 ⇒ 跑几发就会触发 `chapter_cost_over` 假告警（实测第 2 章 3.51 元 / 阈值 0.80 元）。要消掉请在 `cfg['usage_prices']` 里给免费模型登记 0 价。
