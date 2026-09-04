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
; 手动双击升级时程序常还开着，而它锁着自己的 exe：让它先问一句「请关闭应用」，
; 比复制失败后把替换排到下次重启好（症状是「升级了但行为还是旧的」）。
CloseApplications=yes
; 关掉安装器自己的「重启应用程序」：[Run] 已经给了「立即运行」勾选，两处都启动会
; 撞上单实例锁——第二个进程 raise 一下就退出，用户看到的是「更新完程序打不开」。
RestartApplications=no
; 代码签名占位（D2：证书到位后取消注释并配置 Sign Tool）
;SignTool=signtool
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
; 升级安装不卸载用户数据（数据在 ~/.qianbi_novel，与程序目录分离）

[Languages]
; 简体中文翻译随仓库分发（Inno Setup 6.7+ 不再内置翻译文件，避免依赖安装目录）
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[InstallDelete]
; 覆盖安装先清空上一版程序树：只「新的盖旧的」会让已删除/改名的模块留在 _internal 里，
; 和新版拼成一套谁也没测过的组合（症状：升级后行为诡异、查不出原因）。
; 删的都是本安装器自己放进去的程序文件；书稿与配置在用户目录，不在此列。
Type: filesandordirs; Name: "{app}\_internal"

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

[Code]
// 注意：[Code] 段是 Pascal 源码，不认 ini 段那种 ; 行注释（会在注释行报 'BEGIN' expected）。
// 覆盖安装绝不吃掉书稿：安装目录若落在写作数据上，拦下来。
// 「一本书」的判定口径与 app/project.py 的 is_project 一致（四个子目录齐全）。
function IsBookRoot(Dir: String): Boolean;
var
  D: String;
begin
  D := AddBackslash(Dir);
  Result := DirExists(D + '设定') and DirExists(D + '大纲')
            and DirExists(D + '正文') and DirExists(D + '追踪');
end;

function HasBookInside(Dir: String): Boolean;
var
  Find: TFindRec;
  D: String;
begin
  Result := False;
  D := AddBackslash(Dir);
  if FindFirst(D + '*', Find) then
  begin
    try
      repeat
        if (Copy(Find.Name, 1, 1) <> '.') and IsBookRoot(D + Find.Name) then
          Result := True;
      until not FindNext(Find);
    finally
      FindClose(Find);
    end;
  end;
end;

function LooksLikeWritingData(Dir: String): Boolean;
begin
  Result := (Dir <> '') and (IsBookRoot(Dir) or HasBookInside(Dir)
              or FileExists(AddBackslash(Dir) + 'config.json'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    // 该页上 WizardDirValue 还没回写，取用户真正填的那个框
    Dir := WizardForm.DirEdit.Text;
    if LooksLikeWritingData(Dir) then
    begin
      MsgBox('这个目录里已经有你的书稿或应用配置：' + #13#10 + Dir + #13#10 + #13#10 +
             '千笔的程序文件请装到一个独立目录（默认即可），' +
             '否则安装与卸载都会碰到你的书稿。', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = wpReady then
  begin
    // 升级安装会跳过目录页（沿用上次路径），这里是唯一还能提醒的时机
    if LooksLikeWritingData(WizardDirValue()) then
      MsgBox('当前安装位置看起来装着你的书稿：' + #13#10 + WizardDirValue() + #13#10 + #13#10 +
             '建议点「上一步」换一个独立目录。书稿与配置本身不在安装器写入的文件名里，' +
             '但程序与书混在一个目录会让卸载和备份都变复杂。', mbInformation, MB_OK);
  end;
end;
