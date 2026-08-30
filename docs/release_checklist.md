# 发版 Checklist（千笔一文 Novel）

> 每次对外发版逐项打勾。配套脚本：`scripts/build_release.py`（封装计划 T5.1）

## 0. 前置

- [ ] 版本号已在 `app/__init__.py: __version__` 更新（单一来源）
- [ ] `CHANGELOG.md` 已补本版条目（用户可读语言）
- [ ] 工作树干净（`git status`），提交已推送
- [ ] 若改过共享层（app/core|llm|prompts|presets）：`dual_sync_check.py` 零意外漂移

## 1. 质量闸门

- [ ] `python -m pytest tests/unit -q` 全绿
- [ ] 探针全绿：probe_gate_flow / probe_gate_ui / probe_console / probe_chapter_lock（按改动面选）
- [ ] TUI `run.py --smoke` 全绿（共享层改动时必跑）
- [ ] 涉流水线改动：≥3 章真机小 e2e（产物留档）
- [ ] **禁止 `--skip-tests` / `--skip-probe` 发版**

## 2. 打包

- [ ] `python scripts/build_release.py`（含打包冒烟探针）
- [ ] onedir 体积记录进发版说明（基线：v0.14.0）
- [ ] 便携 zip 解压实测可启动
- [ ] SHA256SUMS.txt 已生成且条目齐全

## 3. 杀软预检（误报预案）

- [ ] 安装包与 exe 上传 [VirusTotal](https://www.virustotal.com/) 查看检出
- [ ] 若被 ≥2 家检出：先本地复检（是否误报）→ [微软提交误报](https://www.microsoft.com/en-us/wdsi/filesubmission) → 等候选后再发
- [ ] 国产三件套实测：360 / 火绒 / 腾讯电脑管家 安装+启动
- [ ] 签名（证书到位后）：signtool 双签名（sha256 + RFC3161 时间戳），exe 与 setup 都签

## 4. 虚拟机验收（干净 Win11 快照）

- [ ] 安装器：安装 → 首启向导出现 → 完成向导
- [ ] 新建项目 → 配置 Key → 跑 1 章（小 e2e）→ 定稿
- [ ] 升级安装（旧版之上）→ 书架/配置保留
- [ ] 卸载 → 程序目录移除、用户数据保留
- [ ] 单实例：双开第二次启动只唤起既有窗口
- [ ] 崩溃对话框：无网/无效 Key 场景不出崩溃弹窗（走正常错误提示）

## 5. 更新通道

- [ ] `latest.json` 已更新（version/url/notes/sha256）并推送到仓库/OSS
- [ ] 旧版本应用内「检查更新」能看到新版（或 404 静默——首次发版属正常）

## 6. 发布物

- [ ] 安装包 + 便携 zip + SHA256SUMS + THIRD-PARTY/PRIVACY/LICENSE 上传到 Releases/网盘
- [ ] Release Notes（用户视角，讲清新功能与已知问题）
- [ ] tag `v{版本}` 推送；CHANGELOG 置顶核对

## 7. 回滚预案

- [ ] 上一版本安装包留存可下载
- [ ] 更新清单可回指旧版本（manifest 改回即完成回滚）
