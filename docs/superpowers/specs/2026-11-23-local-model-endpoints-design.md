# 本地模型端点支持 + 版本命名归一 · 设计（2026-11-23）

## 意图与为什么

两件事，同一轮交付：

1. **版本命名归一**：内部把 0.22 / 0.23 / 0.24 当成大版本各发一次，但对外从未发布。
   用户要求把这条线改成 0.20.x 小版本序列——0.22.0 → 0.20.2、0.23.0 → 0.20.3、
   0.24.0 → 0.20.4；0.25.0 是 0.24.0 的评测/加固轮，并入 0.20.4。对外只发一个
   **v0.20.4**，CHANGELOG 补三段合并说明；不改写既有 130 个提交的历史信息（风险大于收益）。
2. **本地端口支持**：大量用户手上只有 Ollama / llama.cpp / LM Studio 这类本机服务。
   现在这些用户必须走「自定义」并自己猜端口、自己处理 `127.0.0.1:11434` 这种无协议头地址，
   而 `test_connection` 对畸形端口会抛未捕获的 `httpx.InvalidURL`（审查实测）。

## 目标 / 非目标

**目标**
- 设置页服务商下拉出现 6 条本地预设：Ollama 11434 / llama.cpp 8080 / LM Studio 1234 /
  vLLM 8000 / KoboldCpp 5001 / text-generation-webui 5000；选中即填 `http://127.0.0.1:<port>`。
- 本地端点免 API Key：判定收口到一个函数，覆盖 `localhost`、`127.0.0.1`、`[::1]`、
  `0.0.0.0`、`::1`，以及 `host:port` 无协议头写法；远端域名后缀伪装（`localhost.evil.com`）不算本地。
- 无协议头的本地地址自动补 `http://`；`check_base_url` 仍负责补 `/v1`，幂等。
- 「测试连接」「拉取」对本地端点可用；Ollama 在 `/v1/models` 不可用时回退 `/api/tags`。
- 「扫描本地端口」按钮：并发探测上述 6 个端口，列出「服务 · 端口 · 模型数」，点一条即填入表单
  （地址、模型、清空 Key），全程不阻塞界面。
- 修 `InvalidURL` 未捕获：畸形端口/方括号一律翻成中文 `LLMError`，不再穿到 `_NetWorker` 崩溃。

**非目标**
- 不实现 Ollama 原生 `/api/chat` 协议（统一走 OpenAI 兼容 `/v1`）。
- 不做模型下载/管理、GPU 检测、局域网发现；只探本机回环。
- 不改内置提示词、不动写作质量参数；远端连接请求体逐字节不变。
- 不构建安装包、不改 `latest.json`（本次只推代码 + tag + Release 说明；安装包另开一轮）。

## 约束

- Windows + PySide6/QML + Python 3.13；不新增第三方依赖（httpx / 标准库够用）。
- 免 Key 只对回环地址开放；远端仍要求 Key，且不允许把 http 明文当远端默认。
- 现有远端连接、既有单测、探针行为不得变化；`PROVIDERS` 的 `builtin=True` 条目仍走 https 校验。
- 版本号唯一来源仍是 `app/__init__.py:__version__`，本次改为 `0.20.4`。
- 沙箱下 pytest 的 `tmp_path` 不可用（WinError 5）；纯函数测试照跑，涉及临时目录的用例交给 CI。

## 方案（三选一，已选 B）

- **A 最小**：只加预设 + 免 Key 收口 + URL 归一。改动最小，但用户仍要知道端口，`[::1]` 之外
  的写法仍会踩坑。
- **B 完整（选中）**：A + 扫描本地端口 + Ollama `/api/tags` 回退 + `InvalidURL` 兜底。
  多出的成本集中在一个纯函数模块与一个后台线程，收益是「装了 Ollama 就能一键接上」。
- **C 仅预设**：不碰判定逻辑；`127.0.0.1:11434` 与 `[::1]` 仍失败，等于埋雷。

## 已定的实现细节

- 新模块 `app/llm/local.py`：`LOCAL_SERVICES`、`normalize_local_url`、`is_local_host`、
  `is_local_base_url`、`needs_api_key`、`parse_openai_models`、`parse_ollama_tags`、
  `probe_service`、`scan_ports`（`ThreadPoolExecutor` 并发，默认 0.6s/端口）。
- `providers.py`：6 条本地预设 `builtin=False`、`base_url=http://127.0.0.1:<port>`、
  `models=[]`、带 hint；排在 `custom` 前。
- `client.py`：`check_base_url` 先做本地归一；`_is_local_template_host` 复用 `is_local_host`；
  `list_models` 本地失败回退 `/api/tags`；`test_connection` 捕 `InvalidURL`/`ValueError`，
  本地成功回执带模型数。
- `router.py` 与 `bridge.py` 两处免 Key 判断改 `needs_api_key`。
- `bridge.py`：`scanLocalPorts()` + `_LocalScanWorker(QThread)` + `localScanResults` 属性；
  QML 在 Base URL 行加「扫描本地」按钮与结果列表。

## 留给实现者的

- 扫描结果的排序与文案细节；QML 结果列表的具体视觉（沿用 `AppButton` 既有样式）。
- Ollama 回退的触发条件（`/v1/models` 非 200 或 JSON 解析失败时尝试 `/api/tags`）。
- 版本重命名的机械脚本（内容 + 文件名），以 `git grep` 复核零残留为准。
