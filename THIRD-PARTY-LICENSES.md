# 第三方组件声明（THIRD-PARTY LICENSES）

千笔一文 Novel 基于 MIT License 发布。本应用分发包包含以下第三方组件，在此致谢并按其原始许可证声明：

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| [Python](https://www.python.org/) | 3.13 | [PSF License](https://docs.python.org/3/license.html) | 运行时 |
| [PySide6](https://www.qt.io/) | 6.x | [LGPL-3.0](https://www.qt.io/licensing/) | GUI 框架（Qt / QML） |
| [PyInstaller](https://pyinstaller.org/) | 6.x | [GPL with bootloader exception](https://pyinstaller.org/en/stable/license.html) | 打包（bootloader 例外允许闭源分发，本项目为 MIT） |
| [httpx](https://www.python-httpx.org/) | 0.x | [BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) | LLM API 客户端 |
| [keyring](https://github.com/jaraco/keyring) | 25.x | [MIT](https://github.com/jaraco/keyring/blob/main/LICENSE) | API key 凭据管理器存储 |
| [cryptography](https://cryptography.io/) | 4x | [Apache-2.0 / BSD-3](https://github.com/pyca/cryptography/blob/main/LICENSE) | 随 keyring 间接引入 |
| [psutil](https://github.com/giampaolo/psutil)（如随包） | 5.x+ | [BSD-3-Clause](https://github.com/giampaolo/psutil/blob/master/LICENSE) | 内存采样（长跑稳定性） |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 6.x | [Inno Setup License](https://jrsoftware.org/files/is/license.txt) | 安装器（仅构建期） |
| [MiSans](https://hyperos.mi.com/font) | 3.x | [MiSans 字体知识产权许可协议](https://hyperos.mi.com/font)（全网免费商用，允许嵌入分发） | 内置界面字体（assets/fonts：Regular/Medium/Demibold/Bold） |
| [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) | 27d2923（2026-08-24 快照） | [MIT License](app/vendor/lieflat-less-ai-tone/LICENSE)，Copyright (c) 2026 shiujan | 去 AI 味规则内核（app/vendor/lieflat-less-ai-tone/；本项目含衍生适配——裁剪交互节、改写边界措辞，**适配部分同样遵循 MIT**） |

> 说明：
> - PySide6 以 LGPL-3.0 动态链接方式使用（PyInstaller onedir 保留独立 DLL，用户可替换 Qt 库），符合 LGPL 义务；Qt 的大多数源可经 https://www.qt.io/ 获取。
> - Textual（TUI 版依赖）不在 GUI 安装包内。
> - 各组件的完整许可证文本以其官方仓库为准；如需离线查阅，可在 Python 环境中执行 `pip-licenses` 生成全量清单。

任何第三方组件的商标归其各自所有者所有。本项目与 Qt Company、DeepSeek、阿里云等无隶属关系。
