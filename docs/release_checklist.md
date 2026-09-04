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
- [ ] 改过界面：`python tests/probe_qml_compile.py`（build_release 已必跑。QML 属性写错会让
      整棵界面树静默加载失败，单测与 prompt 基线都看不见它）
- [ ] 改过更新链路：`python tests/probe_update_ui.py`（40 项、零真网络：通道回退、逐条死因、
      未验签不给安装按钮、离线导入、本机包哈希、限流、设置白名单、面板溢出）
- [ ] 改过关于页：`python tests/probe_about_ui.py`
- [ ] 更新功能不碰 LLM prompt：`probe_prompt_baseline` 必须仍是**零漂移**（漂了就是改错地方了）
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
- [ ] 代码签名：配 `QIANBI_SIGN_PFX`（+ `QIANBI_SIGN_PASS` / `QIANBI_SIGN_SUBJECT`）或
      `QIANBI_SIGN_SHA1`，且 `signtool.exe` 可达 → `build_release.py` 会自动签主程序与安装包
      （SHA-256 摘要 + RFC3161 时间戳）。**证书与口令绝不入库**；pfx 口令走 argv，
      共享 CI runner 上必须换成存储引用（`QIANBI_SIGN_SHA1`）
- [ ] 没配证书时流水线打 `[SKIP]` 并照常出包 —— 此时 README / 更新面板 / Release 正文
      **必须写明 SmartScreen 的点击路径**（「更多信息 → 仍要运行」+ 核对 SHA-256）

## 4. 虚拟机验收（干净 Win11 快照）

- [ ] 安装器：安装 → 首启向导出现 → 完成向导
- [ ] 新建项目 → 配置 Key → 跑 1 章（小 e2e）→ 定稿
- [ ] 升级安装（旧版之上）→ 书架/配置保留；`{app}\_internal` 已清空重建（无上一版残留文件）
- [ ] 故意把安装位置指到某本书的目录 → 目录页拦下不让继续
- [ ] 卸载 → 程序目录移除、用户数据（`~/.qianbi_novel` 与书稿目录）保留
- [ ] 单实例：双开第二次启动只唤起既有窗口
- [ ] 崩溃对话框：无网/无效 Key 场景不出崩溃弹窗（走正常错误提示）

## 5. 更新通道

- [ ] `latest.json` 由 `build_release.py` 自动回填并 **Ed25519 签名**；
      `python scripts/sign_manifest.py --verify latest.json` 必须 VERIFY OK
      （缺签名密钥时闸门要**大声 WARN 且不产出可自动安装的包**，不能静默出一个没背书的清单）
- [ ] 顶层兼容字段 `version/url/sha256` 与 `assets.setup.*` 逐字相等
      —— 不然 v0.15~0.17 的老客户端会拿到「发布页 URL + exe 哈希」这种对不上的组合
- [ ] 清单里的 setup sha256 与本次实际产出的 `...-setup.exe` 复核一致（单测只验格式，指错包它看不见）
- [ ] GitHub Pages 已开且能吐清单：`curl -I https://<user>.github.io/<repo>/latest.json` 返 200，
      仓库根有 `.nojekyll`（否则 Jekyll 会处理这份 json）
- [ ] **反向验证**：手改清单里 `version` 的任意一个字节再跑 `--verify` → 必须拒签。
      没做过这一条，就等于验签路径从没被真实数据跑通过
- [ ] 开机自动检查默认开 + 24h 限流 + 一次性告知 + `auto_check_chosen` 迁移，
      由 `probe_update_ui.py` 覆盖（`QIANBI_OFFLINE` 下必须零请求）

## 5b. 真机升级矩阵（离线证明不了，必须实跑并如实报告）

- [ ] **安装版 + 空闲**：一键「下载并校验 → 立即安装」全流程走通，装完自动重开、书架与配置在
- [ ] **安装版 + 脏稿**：编辑器有未保存内容时走一键升级 —— 不该卡成「需要重启计算机」，
      且确认步承诺的「草稿保留、下次可恢复」要真的能恢复
- [ ] **便携版**：面板只给链接与哈希，**不出现**「立即安装」
- [ ] **旧进程还开着时覆盖安装**（v0.17 → 本版）：Restart Manager 问一句，而不是静默排到重启
- [ ] **断网离线路径**：禁用网络 → 导入拷来的 `latest.json` → 选本地 `setup.exe` →
      哈希命中才出安装 → 装上
- [ ] **SmartScreen**：真实下载后双击，确认蓝底提示出现、文档写的「更多信息 → 仍要运行」走得通
- [ ] **陈旧代理**：把系统代理设成一个死地址 → 检查仍应通过「无代理第二遍」成功
- [ ] 未验签清单（自签一份）导入后：能看说明与哈希，但**没有任何可执行按钮**

## 6. 发布物

- [ ] 安装包 + 便携 zip + SHA256SUMS + THIRD-PARTY/PRIVACY/LICENSE 上传到 Releases/网盘
- [ ] Release Notes（用户视角，讲清新功能与已知问题）
- [ ] tag `v{版本}` 推送；CHANGELOG 置顶核对

## 7. 回滚预案

- [ ] 上一版本安装包留存可下载
- [ ] 清单可回指旧版本：改回 `latest.json` 后**必须重新 `sign_manifest.py` 签名**
      —— 未签名的回滚清单只会被显示、不会被安装（这是设计，不是 bug）。
      用户机器上的更新缓存每次读取都重验，所以回滚会自愈，不用远程清缓存
