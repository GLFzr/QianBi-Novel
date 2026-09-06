# 参与开发 · CONTRIBUTING

欢迎来搭这条流水线。公测期间作者当天会回 Issue；动手写代码前先读一遍下面的规矩，能让你的 PR 第一轮就过。

## 路由

- **Bug** → [Issue（bug 模板）](https://github.com/GLFzr/QianBi-Novel/issues/new/choose)
- **功能设想 / 用法讨论** → [Discussions · Ideas](https://github.com/GLFzr/QianBi-Novel/discussions)（大的改动先聊设计再动手）
- **晒你的书 / 找同好** → [Discussions · Show and tell](https://github.com/GLFzr/QianBi-Novel/discussions)

## 环境

```bash
git clone https://github.com/GLFzr/QianBi-Novel.git
cd QianBi-Novel
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python run.py
```

## 提交前闸门（PR 必须全绿）

```bash
.venv/Scripts/python -m pytest tests/unit -q        # 离线单测，约 3 秒
.venv/Scripts/python tests/probe_qml_compile.py     # 动过 UI/QML 就跑
```

- 动了**提示词装配**（`app/prompts/`、预设字段、装配层）：`tests/probe_prompt_baseline.py` 会红，
  逐字确认 diff 是你有意为之后 `--update-baseline`，并在 PR 里说明改了哪条链路；
- 动了**共享业务核心**（`app/core`、`app/llm`、`app/prompts`、`app/presets`、`app/wb.py`）：
  必须跑 `scripts/dual_sync_check.py`，与 `qianbi-Novel-TUI` 双端同步（水印机制见 README「开发」一节）；
- 新功能请带测试：纯逻辑进 `tests/unit`，链路行为写成 `probe_*.py`。

## 提交与 PR

- Commit 遵循 conventional commits（仓库历史是 `feat:` / `fix:` / `docs(changelog):` 风格）；
- PR 小步提交，说明**动机**与**验证方式**（跑了哪些单测/探针）；
- 版本号唯一来源是 `app/__init__.py` 的 `__version__`，发版由维护者走 `scripts/build_release.py` 流水线，PR 不用动版本。

## 一条家规

这个仓库最看重「证据能被机器钉住」：能写成确定性断言的，不要写成提醒；
能进探针的，不要只写在 PR 描述里。这条贯穿全仓（引证验真、prompt 基线、双端水印都是它），
新代码请顺着同一方向长。

## License

提交即同意以 [MIT](LICENSE) 授权你的贡献。
