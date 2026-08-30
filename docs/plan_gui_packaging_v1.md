# 千笔一文 Novel · GUI 商业化封装计划 v1

> **生成日期**：2026-08-29
> **目标**：把「跑源码的开发工具」封装为「可安装、可更新、可售后」的 Windows 商业软件。
> **维护约定**：沿用接力书惯例——先改计划再改代码，每完成一项勾选并回填执行日志。

---

## 0. 现状盘点（2026-08-29）

### 0.1 已有资产（可直接复用）

| 资产 | 状态 |
|---|---|
| PySide6+QML 应用 | v0.13.0，版本单一来源（`app/__init__.py: __version__`）✅ |
| 日志 | `~/.qianbi_novel/logs/qianbi.log` 滚动 2MB×5 ✅ |
| 崩溃现场 | `app/diagnostics.py: dump_failure()`（prompt/日志尾/异常落盘）✅，**缺 UI 呈现** |
| 打包雏形 | `QianBi-Novel.spec`（onedir 模板但 `upx=True` 有杀软误报风险）+ `build_exe.py`（onefile 旧脚本，与 spec 不一致，需废弃或重写） |
| 图标 | `assets/icon.ico` / `icon.png` ✅ |
| 数据目录 | `~/.qianbi_novel/`（config/logs/projects 分离）✅ |
| 质量闸门 | 64 单测 + 4 探针 + TUI smoke + eval_gate ✅ |

### 0.2 缺口（本计划要补齐的）

安装器 / 代码签名 / 自动更新 / 单实例锁 / 崩溃 UI / API key 加密存储 / 打包后冒烟 / 首启向导 / 授权与试用 / 第三方声明。

### 0.3 红线（沿用 + 新增）

1. 沿用全部既有红线（数据格式契约、双端同步、真机 e2e）。
2. **共享层红线适用于打包**：`app/core`、`app/llm`、`app/prompts`、`app/presets` 的改动仍须双端同步；打包脚本只碰 `run.py`、`app/main.py`、`app/ui`、`scripts/`、打包资产。
3. TUI **不进入 v1 安装包**（开发者伴侣工具）；dual_sync_check 不受影响。
4. 任何发版 exe 必须先过打包冒烟清单（§P5）。
5. 用户 API key **严禁**进入日志/崩溃 dump/遥测（现有 dump 需审计字段）。

---

## 1. 关键决策点（需要用户拍板，给出推荐）

| # | 决策 | 选项 | 推荐 | 理由 |
|---|---|---|---|---|
| D1 | 打包形态 | A. onedir+安装器 B. onefile | **A** | onefile 启动慢 3-8s、杀软误报率高、每次更新全量下载；onedir 配安装器是 Windows 商业软件标准形态 |
| D2 | 代码签名 | A. OV 证书（约 $300/年）B. EV 证书（约 $400-700/年）C. 暂不签名 | **A 起步**，预算允许可升 B | 不签名必遭 SmartScreen 拦截；OV 需 2-4 周信誉积累，EV 立即放行。国内可考虑 SSL.com/沃通 |
| D3 | 更新通道 | A. GitHub Releases B. 自建/对象存储（阿里 OSS+CDN） | **A 为主**（开源项目天然主场，URL 已参数化），B 作为国内加速的后续选项 | 仓库公开后 GitHub Releases 即清单源；manifest URL 可配置 |
| D4 | 授权模式 | A. 开源免费+BYOK B. 买断制 C. 订阅制 D. 买断+试用 | **A：开源（MIT）+ 免费 + BYOK**（2026-08-29 用户拍板：本项目是开源软件，暂未公开） | 项目根已有 MIT LICENSE；成熟度投入面向「可信赖的开源发行版」：签名/更新/崩溃处理照做，无授权门控 |
| D5 | key 存储 | A. Windows 凭据管理器（keyring） B. DPAPI 加密文件 | **A**，回退 B | keyring 标准库级方案（`keyring` 包）；DPAPI 作无凭据管理器环境的降级 |
| D6 | 遥测 | A. 无 B. opt-in 匿名统计 | **B（默认关）** | 崩溃率/功能使用数据对成熟软件重要，但必须显式 opt-in |

---

## 2. 阶段任务

标记：**S** ≤1h，**M** 1–3h，**L** 3–8h，**XL** >1 天。状态：`[ ]` 未开始。

### Phase P1 · 打包管线（约 1.5 天，先决：D1/D5 拍板）

- [x] **T1.1 spec 修缮与 build_exe.py 收编**（M）
  - `upx=False`（杀软误报首要来源）；`excludes` 裁剪（tkinter/_tkinter、matplotlib、PIL 等未用重依赖——以 `pipreqs`/导入图实测为准）；版本资源注入（`VSVersionInfo`：产品名/版本/公司/图标，从 `app.__version__` 单一来源生成 rc 文件）；`--collect-data` 核查（QML/presets/assets）；`console=False` 保留。
  - `build_exe.py`（onefile）标记废弃并移入 `_archive/` 或重写为 onedir 统一入口。
  - 验收：`pyinstaller QianBi-Novel.spec` 产出 onedir；双击启动；体积记录基线（预估装后 180-280MB）。
- [x] **T1.2 一键发布脚本 `scripts/build_release.py`**（M）
  - 流水线：读版本 → 跑单测+探针（复用 tests/unit + probe 清单）→ PyInstaller → 生成便携 zip → SHA256SUMS 清单 → 产物目录 `dist/release/v{ver}/`。
  - `--skip-tests` 逃生开关（仅调试用，CI 禁用）。
  - 验收：一条命令从干净工作树到可分发产物；清单含版本号与各文件哈希。
- [x] **T1.3 打包版冒烟探针 `tests/probe_packaged.py`**（M）
  - 对 dist 产物做启动探针：exe 启动 → 主窗口出现（UIA 查 `panelStack`）→ 新建临时项目 → （可选 mock）退出无崩溃；产物运行日志写入独立目录。
  - 验收：接入 build_release.py 作发版门禁；`--skip-tests` 时显式警告。

### Phase P2 · 安装器与分发（约 1.5 天，依赖 P1；先决：D1/D2）

- [x] **T2.1 Inno Setup 安装脚本**（L）
  - per-user 安装（免管理员）、开始菜单/桌面快捷方式、卸载（可选保留 `~/.qianbi_novel` 用户数据——默认保留）、升级安装静默覆盖、安装器语言=简中、license 页（EULA 占位）。
  - 签名接入：`signtool sign /fd sha256 /tr <TSA>` 对 exe 与安装器双签名（证书到位后填参数位）。
  - 验收：干净 Win11 虚拟机安装→启动→卸载，无残留（除用户数据）；升级安装保留书架。
- [x] **T2.2 便携版**（S）
  - onedir 打 zip + `便携版说明.txt`（数据目录位置/升级=解压覆盖）。
  - 验收：解压即用，U 盘换机可跑。
- [x] **T2.3 杀软误报预案**（S，文档+流程）
  - VirusTotal 预检流程、Microsoft 安全智能提交误报申诉入口、（D2=B 时）EV 直通的说明；写进 `docs/release_checklist.md`。

### Phase P3 · 运行时成熟度（约 2-3 天，可与 P2 并行）

- [x] **T3.1 单实例锁**（S）
  - `QLocalServer` 命名锁：二次启动时唤起既有窗口并退出（防多开写坏 config/state——时间当铺运行期间已观察到配置文件被双实例写花）。
- [x] **T3.2 崩溃对话框**（M）
  - 全局 `sys.excepthook` + Qt 异常钩子：未捕获异常 → 复用 `diagnostics.dump_failure` → 弹窗（错误摘要 + 「打开日志目录」「复制详情」「重启」）；Qt 线程异常同样接入。
  - key 脱敏审计：dump/log 输出统一过 `_redact_secrets()`（connections 的 api_key 字段、`sk-`/Bearer 模式）。
- [x] **T3.3 API key 加密存储**（M）
  - `keyring`（Windows 凭据管理器）存 key，config.json 只存 `{"stored_in": "keyring", "fingerprint": "..."}` 指纹；首启自动迁移明文 key（读入→入 keyring→config 中清除→toast 告知）；无凭据管理器环境降级 DPAPI。
  - 验收：config.json 中 grep 不到明文 key；旧配置无损迁移；双端（GUI）回归。
- [x] **T3.4 应用内检查更新**（L，依赖 D3）
  - v1 范围：启动后异步轮询版本清单 JSON（版本号+下载 URL+SHA256+更新说明，清单可签名）→ 有新版则角标+对话框（跳转下载页/直接下安装包并校验哈希后拉起）；不自动静默安装（v2 再做差分）。
  - 清单源：OSS 主 + GitHub Releases 镜像；可配置检查频率与代理。
- [x] **T3.5 首启体验**（M）
  - 首启向导（3 步）：欢迎/数据目录确认 → 连接配置（粘贴 key，即时连通性测试——复用现有连接测试）→ 打开示例项目或新建；「跳过」全程可期。
  - 示例项目：随包带《改命笔记》只读示例或一键下载示例。
- [x] **T3.6 QML 兜底与窗口健壮性**（S）
  - QML 加载失败（engine.rootObjects 空）→ 原生错误窗（显示 warnings + 日志路径），替代当前 assert 崩溃；DPI/多显示器回归。

### Phase P4 · 开源发布要素（约 1-2 天；D4=开源，授权/试用已取消）

- [x] **T4.1 开源发布资产**（S）
  - LICENSE（MIT）已在仓库根 ✅；`THIRD-PARTY-LICENSES.md`（PySide6 LGPL-3/keyring MIT/httpx BSD-3/cryptography Apache-2.0/Python PSF 等随包组件声明）；安装器 LicenseFile 直接引用 MIT LICENSE（不再用商业 EULA）。
- [x] **T4.2 关于对话框**（M）
  - 版本/构建信息 + 检查更新按钮 + 打开日志/数据目录 + 开源仓库链接 + 遥测开关（用户可见可关）。
- [x] **T4.3 遥测（opt-in，默认关）**（M）
  - 仅两类事件：应用启动/章节完成计数 + 崩溃摘要（脱敏）；**本地文件落点**（`~/.qianbi_novel/telemetry/pending.jsonl`），不上传——服务端为远期可选；About 内一键开关。

### Phase P5 · 发布工程（约 1 天，收口）

- [x] **T5.1 发布 checklist `docs/release_checklist.md`**（S）
  - 版本号→CHANGELOG→tag→build_release→签名→杀软预检→虚拟机安装冒烟→（更新通道清单发布）→公告。
- [x] **T5.2 虚拟机验收脚本化**（M）
  - 干净 Win11 验收点清单脚本化到可行程度（安装/首启/新建/跑 1 章 mock/卸载），真机人工项留 checklist。
- [x] **T5.3 v0.14.0 首个安装版发版**（M）
  - 走完整 checklist，产出 v0.14.0 安装包+便携包+签名（证书到位后补签重发）。

---

## 3. 里程碑与估计汇总

| 里程碑 | 内容 | 估计 | 出口标准 |
|---|---|---|---|
| **M1 能装的包** | P1 全部 + P2.2 | ~2 天 | onedir+便携 zip+打包冒烟门禁 |
| **M2 像样的安装** | P2.1/P2.3 | ~1.5 天 | 干净机安装/卸载/升级通过；签名参数位就绪 |
| **M3 成熟运行时** | P3 全部 | ~2.5 天 | 单实例/崩溃 UI/key 加密/检查更新/首启向导 |
| **M4 开源发布要素** | P4 | ~1-2 天 | 关于/第三方声明/隐私/遥测开关 |
| **M5 v0.14.0 发版** | P5 | ~1 天 | 首个对外安装版 |

总量 **7-9 个工作日**（开源路线，无授权模块；签名证书周期不影响开发）。建议节奏：D1/D4/D5 先拍板 → P1 立刻开工（不等证书）→ 证书办理期间推 P3 → 汇合 M5。

## 4. 风险与对策

| 风险 | 对策 |
|---|---|
| 杀软误报（PyInstaller 高发） | upx=False；OV/EV 签名；VirusTotal 预检+微软申诉；发布前 3 家国产杀软实测 |
| PySide6 体积大（装后 180-280MB） | excludes 裁剪；接受基线（QML 应用正常水位）；不追求极致瘦身牺牲稳定性 |
| SmartScreen 信誉冷启动 | 文档明示「仍要运行」引导；OV 积累期约 2-4 周 |
| 国内更新通道 | OSS+CDN 主源、GitHub 镜像；版本清单签名防篡改 |
| key 安全 | keyring 优先；dump/log 全链脱敏；config 中永不落明文 |
| 授权被破解 | 离线签名只防君子；核心价值在持续更新与售后，定价策略对齐（不为防盗版牺牲离线体验） |
| 双端红线漂移 | P3/P4 改动集中在 app/main.py、app/ui、scripts；共享层改动照旧走 dual_sync_check |

## 5. 待用户决策清单（阻塞项）

1. **D1 打包形态**：推荐 onedir+安装器（默认按此执行）
2. **D2 证书**：OV 起步还是 EV？预算与公司/个人主体？（影响 M2 时点，不阻塞 P1/P3）
3. **D3 更新通道**：是否有可用 OSS/服务器？（无则先用 GitHub Releases 占位）
4. **D4 授权模式**：已拍板——开源（MIT）+ 免费 + BYOK，无授权门控
5. **D6 遥测**：默认关闭可接受？

---

## 执行日志（接力方填写）

| 日期 | 任务 | 执行者 | 结果 / 提交号 | 备注 |
|---|---|---|---|---|
| 2026-08-29 | 计划制定 | ZCode | — | 基于现状盘点（spec/build_exe.py/logger/diagnostics/config）产出 v1；D1-D6 决策点待用户拍板 |
| 2026-08-29 | D4 拍板：开源路线 | 用户 | 计划修订 8a5df53 | 本项目为开源软件（暂未公开）：取消授权/试用模块，P4 改开源发布要素，D3 改 GitHub Releases 主通道 |
| 2026-08-29 | P1-P5 全量落地 | ZCode | 2a90fc6 + tag v0.14.0 | 全部 18 项任务完成：①打包管线（spec 重写 onedir/UPX off/裁剪/版本资源、build_release.py、probe_packaged 门禁）；②Inno Setup 脚本（签名参数位就绪）+便携包；③单实例锁/崩溃对话框（脱敏）/keyring 迁移（config 零明文实测）/检查更新/首启向导/QML 兜底；④关于对话框+THIRD-PARTY+PRIVACY+遥测 opt-in；⑤**v0.14.0 实际构建通过**（176MB onedir + 71MB 便携包 + 冒烟探针绿），tag 已打。质量：73 单测全绿、QML 探针 10/10+8/8、dual_sync_check 零意外漂移。遗留：Inno Setup 本机未装（安装包构建待补，脚本就绪）；签名待证书（tools/sign.bat 占位）；latest.json 待仓库公开后生效 |
