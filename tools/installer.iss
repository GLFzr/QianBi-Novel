; 千笔一文 Novel — Inno Setup 安装脚本（封装计划 T2.1）
; 编译：ISCC /DAppVersion=<app/__init__.py 的 __version__> tools/installer.iss
;      （正常发版由 scripts/build_release.py 自动注入，无需手写版本号）
; 签名（证书到位后在 Sign Tool 配置或本脚本 SignToolDirective 启用）：
;   signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 <file>

#define AppName "千笔一文 Novel"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#define AppExe "QianBi-Novel.exe"

[Setup]
AppId={{8C6E3F2A-52B7-4E0E-9E8A-QIANBI0000000}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
DefaultDirName={autopf}\QianBi-Novel
; 开源免费软件：per-user 安装（免管理员）；PrivilegesRequired=lowest 时 autopf 映射到 %LocalAppData%
PrivilegesRequired=lowest
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
OutputDir=..\dist\release\v{#AppVersion}
OutputBaseFilename=QianBi-Novel-v{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
; 代码签名占位（D2：证书到位后取消注释并配置 Sign Tool）
;SignTool=signtool
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
; 升级安装不卸载用户数据（数据在 ~/.qianbi_novel，与程序目录分离）

[Languages]
; 简体中文翻译随仓库分发（Inno Setup 6.7+ 不再内置翻译文件，避免依赖安装目录）
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\dist\QianBi-Novel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 用户数据 ~/.qianbi_novel 默认保留（书稿与配置）；如需彻底清理请手动删除该目录

[Messages]
WelcomeLabel2=这将安装 [name/ver] 到你的电脑。%n%n一款运行在本机的 AI 网文自动写作台：自带模型 Key、数据不出本机、开源（MIT）。%n%n建议关闭其他正在运行的千笔一文窗口后继续。
