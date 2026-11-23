# 本地模型端点 + 0.20.4 版本归一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 本机只安装了 brainstorming / writing-plans / test-driven-development / systematic-debugging / grilling；
> 执行阶段用 `todo_write` 跟踪，不走未安装的 skill。

**Goal:** 把内部 0.22/0.23/0.24 归一到 0.20.2/0.20.3/0.20.4，并为设置页加入 Ollama、llama.cpp 等本机端点的预设、免 Key、扫描与模型发现，最后推 GitHub 并打 v0.20.4。

**Architecture:** 新增纯函数模块 `app/llm/local.py`（URL 归一/本地判定/端口探测/模型解析），由 `client.py`、`providers.py`、`router.py`、`bridge.py` 消费；扫描在 QThread 里跑，QML 只读结果。版本串在代码/文档/文件名中机械替换，不改提交历史。

**Tech Stack:** Python 3.13、httpx、PySide6/QML、pytest、标准库 `concurrent.futures`。

**Spec:** `docs/superpowers/specs/2026-11-23-local-model-endpoints-design.md`

## Global Constraints

- 版本唯一来源 `app/__init__.py:__version__ = "0.20.4"`；tag `v0.20.4`。
- 映射：0.22.0→0.20.2、0.23.0→0.20.3、0.24.0→0.20.4、0.25.0→0.20.4、计划中的 0.21→0.20.2。
- 本地预设：`builtin=False`、`http://127.0.0.1:<port>`、`models=[]`，不得进 `DEFAULT_CONNECTIONS`。
- 免 Key 仅限回环（localhost / 127.0.0.1 / ::1 / 0.0.0.0 / ::），远端一律仍要 Key。
- 不新增第三方依赖；不改 `latest.json`；不构建安装包。
- 既有远端连接的请求体/行为不得变化；现有单测除已知环境红（tmp_path）外不得新增红。

## Review Focus

- `[::1]`、无协议头 `127.0.0.1:11434`、畸形端口：不得抛未捕获异常，不得把远端当本地。
- 本机服务在线但零模型：回执必须是「连上了但还没有模型」，不能显示成可写作。
- 扫描：6 个端口全不通时 ≤ 2 秒返回，界面不冻结；结果点击必须清空 Key 字段。
- `localhost.evil.com`、`192.168.1.5`：不得免 Key。
- 版本替换后：旧串（0.22.0/0.23.0/0.24.0/0.25.0）在受版本管理的文本里零残留。

---

### Task 1: 提交工作树 P0 批与仓库卫生

**Files:**
- Modify: `.gitignore`
- Revert: `pipeline_state.json`
- Commit: `app/core/{gates,ledger_view,rewrite_gate,span_edit,stages}.py`、`app/llm/client.py`、`app/usage.py`、`tests/long_run.py`、`tests/unit/test_*.py` 新增/修改、`docs/OpenCode_Go免费模型使用指南.md`

**Steps:**
- [ ] 复核 `git diff`：确认改动就是 0.25.0 台账里的 A1/A2/V7/V8 接线与测试，无夹带。
- [ ] `git checkout -- pipeline_state.json`；`.gitignore` 追加 `_scratch/`、`pipeline_state.json`。
- [ ] 提交：`fix(0.20.4 P0): 正文卫生接线 + 记账出声 + 段号口径 + 净增益闸（原 0.25.0 台账 A1/A2/V7/V8）`。

### Task 2: 版本命名归一

**Files:**
- Modify: `app/__init__.py`、`version_info.txt`、`README*.md`、`docs/**`、`tests/**`、`CHANGELOG.md`
- Rename: `docs/0.22.0_*` → `docs/0.20.2_*`；`docs/0.23.0_*` → `docs/0.20.3_*`；`docs/0.24.0_*` → `docs/0.20.4_*`；`docs/0.25.0_*` → `docs/0.20.4_*`

**Steps:**
- [ ] `git grep -n` 统计旧串；按映射做内容替换（先长串后短串，`v` 前缀一并处理）。
- [ ] `git mv` 改文件名，修 `docs/README.md` 索引链接。
- [ ] `app/__init__.py` 改 `0.20.4`；`version_info.txt` 改 `0, 20, 4, 0`。
- [ ] 复核：`git grep -E "0\.(22|23|24|25)\.0"` 在受管文本里应仅剩历史说明/映射表。
- [ ] 提交：`chore(release): 版本命名归一 0.20.x（0.22→0.20.2 / 0.23→0.20.3 / 0.24→0.20.4 / 0.25→0.20.4）`。

### Task 3: `app/llm/local.py` 纯函数（TDD）

**Files:**
- Create: `app/llm/local.py`
- Test: `tests/unit/test_local_endpoints.py`

**Interfaces:**
- `normalize_local_url(text: str) -> str`
- `is_local_host(host: str) -> bool`
- `is_local_base_url(url: str) -> bool`
- `needs_api_key(conn: dict) -> bool`
- `parse_openai_models(payload: dict) -> list[str]`
- `parse_ollama_tags(payload: dict) -> list[str]`
- `probe_service(port: int, timeout: float, get=None) -> dict | None`
- `scan_ports(timeout: float = 0.6, ports=None, probe=None) -> list[dict]`
- `LOCAL_SERVICES: list[dict]`（每项含 key/label/port/native_path）

**Steps:**
- [ ] 写失败测试：`test_normalize_local_url_adds_http_scheme`、`test_is_local_base_url_rejects_lookalike`、`test_needs_api_key_false_for_ipv6_loopback`、`test_parse_ollama_tags`、`test_scan_ports_reports_up_service`、`test_scan_ports_skips_closed`、`test_probe_service_falls_back_to_ollama_tags`。
- [ ] 跑测试确认红（`ModuleNotFoundError`）。
- [ ] 实现纯函数；默认 `get` 用 `httpx.get`，测试注入假 `get`。
- [ ] 跑 `pytest tests/unit/test_local_endpoints.py -q` 全绿。
- [ ] 提交：`feat(0.20.4): 本地端点纯函数层（URL 归一/免Key判定/端口探测/模型解析）`。

### Task 4: client / providers / 免 Key 收口（TDD）

**Files:**
- Modify: `app/llm/client.py`（`check_base_url`、`_is_local_template_host`、`list_models`、`test_connection`）
- Modify: `app/llm/providers.py`（6 条预设 + `PROVIDER_ORDER`）
- Modify: `app/llm/router.py`、`app/ui/bridge.py`（两处免 Key）
- Test: `tests/unit/test_local_endpoints.py`、`tests/unit/test_providers.py`

**Steps:**
- [ ] 红：`test_check_base_url_normalizes_bare_local_host`、`test_local_presets_are_keyless_and_http`、`test_invalid_url_becomes_llm_error`。
- [ ] 实现：`check_base_url` 先 `normalize_local_url`；`_is_local_template_host` 改调 `local.is_local_host`；`list_models` 本地回退；`test_connection` 捕 `httpx.InvalidURL`/`ValueError`，本地成功带模型数。
- [ ] `providers.py` 加 6 条 `builtin=False` 预设；`PROVIDER_ORDER` 同步。
- [ ] 全绿；确认远端连接 `_chat_url()` 不变。
- [ ] 提交：`feat(0.20.4): 本地端点接入——预设/免Key/URL归一/Ollama回退/InvalidURL兜底`。

### Task 5: 扫描 UI

**Files:**
- Modify: `app/ui/bridge.py`（`_LocalScanWorker`、`scanLocalPorts`、`localScanResults`、`localScanFinished`）
- Modify: `app/ui/qml/SettingsPanel.qml`（Base URL 行「扫描本地」按钮 + 结果列表）
- Test: `tests/unit/test_local_scan_ui.py`（源码钉：槽/信号/按钮存在）

**Steps:**
- [ ] 红：源码钉测试断言 `bridge.py` 有 `scanLocalPorts`、`localScanFinished`，QML 有「扫描本地」与 `localScanResults`。
- [ ] 实现 worker + slot + QML 列表；点击填入 url/provider/model 并清空 Key。
- [ ] QML 编译探针/源码测试全绿。
- [ ] 提交：`feat(0.20.4): 设置页扫描本地端口并一键接入`。

### Task 6: CHANGELOG / README

**Files:**
- Modify: `CHANGELOG.md`（补 `[0.20.4]`、`[0.20.3]`、`[0.20.2]`）
- Modify: `README.md`、`README.en.md`（本地模型章节与版本行）

**Steps:**
- [ ] 0.20.4 段写：本地端点、P0 门禁、0.24 质量包、评测结论与诚实边界。
- [ ] 0.20.3 / 0.20.2 段写：章纲合同/非流式通道/全量实测；撞墙修复/结构还债/引擎第一批。
- [ ] README 加「本地模型（Ollama / llama.cpp / LM Studio）」三步接入。
- [ ] 提交：`docs(0.20.4): CHANGELOG 三段合并 + README 本地模型章节`。

### Task 7: 验证、tag、推送、Release

**Steps:**
- [ ] `pytest tests/unit/test_local_endpoints.py tests/unit/test_providers.py -q` 全绿；相关源码钉测试全绿。
- [ ] `python scripts/check_docs.py`（若可跑）与 `git status` 干净。
- [ ] `git tag -a v0.20.4 -m "..."`。
- [ ] `git push origin main`、`git push origin v0.20.4`（需要时申请 full access）。
- [ ] `gh release create v0.20.4 --title ... --notes-file ...`（不带安装包）。
- [ ] 回报：提交数、测试结果、Release 链接、仍未做的安装包/签字清单。
