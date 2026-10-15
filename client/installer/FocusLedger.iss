; Compile through build-installer.ps1 so the version follows focus_agent/__init__.py.
#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif
#ifndef ClientRoot
  #define ClientRoot ".."
#endif

[Setup]
AppId={{BD0BBACF-4A40-4F25-831E-93EA15A4CC49}
AppName=专注记录 · Focus Ledger
AppVersion={#AppVersion}
AppVerName=专注记录 · Focus Ledger {#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\FocusLedger
DefaultGroupName=专注记录 · Focus Ledger
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=no
WizardStyle=modern
ShowLanguageDialog=no
SetupIconFile={#ClientRoot}\build\icon\FocusLedger.ico
UninstallDisplayIcon={app}\FocusLedger.exe
OutputDir={#ClientRoot}\release
OutputBaseFilename=FocusLedger-Setup-windows-x64
Compression=lzma2
SolidCompression=yes
AppMutex=Local\FocusLedger-{%USERNAME}
SetupMutex=Local\FocusLedger-Setup
CloseApplications=no
RestartApplications=no
UninstallDisplayName=专注记录 · Focus Ledger

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Messages]
SetupAppRunningError=专注记录正在运行。%n%n请在系统托盘中右键点击专注记录图标，选择“退出”，然后点击“确定”继续安装。
UninstallAppRunningError=专注记录正在运行。%n%n请在系统托盘中右键点击专注记录图标，选择“退出”，然后点击“确定”继续卸载。
FinishedLabel=专注记录已安装到您的电脑。%n%n可通过开始菜单打开程序，通过 Windows“设置 → 应用 → 已安装的应用”卸载。升级和卸载会保留当前用户的配置与本地缓存。
ConfirmUninstall=确定要卸载 %1 及其程序文件吗？%n%n配置与本地缓存将保留在当前用户的 LocalAppData\FocusLedger 目录。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#ClientRoot}\dist\FocusLedger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ClientRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ClientRoot}\docs\*.png"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#ClientRoot}\..\docs\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\专注记录"; Filename: "{app}\FocusLedger.exe"; Parameters: "--show"; WorkingDir: "{app}"
Name: "{group}\卸载专注记录"; Filename: "{uninstallexe}"
Name: "{autodesktop}\专注记录"; Filename: "{app}\FocusLedger.exe"; Parameters: "--show"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FocusLedger.exe"; Parameters: "--show"; Description: "启动专注记录"; Flags: nowait postinstall skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  ApprovedKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';

function StartupExecutable(Command: String): String;
var
  First, Delimiter: Integer;
  Separator: Char;
begin
  Command := Trim(Command);
  Result := '';
  if Command = '' then
    Exit;
  First := 1;
  Separator := ' ';
  if Command[1] = '"' then
  begin
    First := 2;
    Separator := '"';
  end;
  { Scan Unicode characters directly: mixed AnsiString/String Pos overloads
    can return byte offsets for Chinese paths with older Pascal Script. }
  Delimiter := First;
  while Delimiter <= Length(Command) do
  begin
    if Command[Delimiter] = Separator then
      Break;
    Delimiter := Delimiter + 1;
  end;
  if (Separator = '"') and (Delimiter > Length(Command)) then
    Exit;
  Result := Copy(Command, First, Delimiter - First);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Command: String;
begin
  { Migrate an existing portable startup entry without enabling startup or
    clearing the user's disabled state in Windows StartupApproved. }
  if CurStep = ssPostInstall then
    if RegQueryStringValue(HKCU, RunKey, 'FocusLedger', Command) then
    begin
      Log('Found an existing FocusLedger startup entry.');
      if CompareText(ExtractFileName(StartupExecutable(Command)), 'FocusLedger.exe') = 0 then
      begin
        if RegWriteStringValue(HKCU, RunKey, 'FocusLedger',
          '"' + ExpandConstant('{app}\FocusLedger.exe') + '" --startup') then
          Log('Migrated the FocusLedger startup path; StartupApproved was preserved.')
        else
          Log('Unable to migrate the existing FocusLedger startup entry.');
      end;
    end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  (* Only remove startup entries owned by this installation. User data lives
     outside {app} and is intentionally never scheduled for deletion. *)
  if (CurUninstallStep = usUninstall) and RegQueryStringValue(HKCU, RunKey, 'FocusLedger', Command) then
    if CompareText(StartupExecutable(Command), ExpandConstant('{app}\FocusLedger.exe')) = 0 then
    begin
      RegDeleteValue(HKCU, RunKey, 'FocusLedger');
      RegDeleteValue(HKCU, ApprovedKey, 'FocusLedger');
    end;
end;
