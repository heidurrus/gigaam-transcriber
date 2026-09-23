; GigaAM Transcriber - Inno Setup Script
; Requires Inno Setup 6.1+: https://jrsoftware.org/isinfo.php
;
; Built by packaging/build.py --target windows-x64, which stages a standalone
; Python with the base layer plus the app into StageDir. Nothing needs to be
; preinstalled on the user's PC; the app's Setup screen installs PyTorch,
; GigaAM, ffmpeg and the speech model on first launch (spec FR-PLAT-04/06).

#define AppName "GigaAM Transcriber"
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef StageDir
  #define StageDir "..\build\windows\stage"
#endif
#define AppPublisher "heidurrus"
#define AppURL "https://github.com/heidurrus/gigaam-transcriber"
; Per-user data folder used by the app (core/paths.py APP_DIR_NAME)
#define DataDirName "RequirementsWorkbench"
#define WebView2Guid "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

[Setup]
AppId={{6C7B8E2A-4F1D-4B8E-9A55-2F7E5D1C3B90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=GigaAM-Transcriber-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
; No admin rights needed: per-user install
PrivilegesRequired=lowest
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\python\pythonw.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\app\*";    DestDir: "{app}\app";    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files from the pre-0.1 layout (Python-on-PATH + .bat launchers)
Type: files; Name: "{app}\setup.bat"
Type: files; Name: "{app}\launcher.bat"
Type: files; Name: "{app}\launcher-browser.bat"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\boot.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\python\pythonw.exe"
Name: "{group}\{#AppName} (Browser Mode)"; Filename: "{app}\python\python.exe"; Parameters: """{app}\app\boot.py"" --browser"; WorkingDir: "{app}\app"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\boot.py"""; WorkingDir: "{app}\app"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\boot.py"""; WorkingDir: "{app}\app"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[Code]
{ The desktop window uses Microsoft Edge WebView2. Windows 11 ships it; some
  Windows 10 PCs don't, so install the Evergreen runtime when it's missing
  (spec FR-PLAT-01 AC5, FR-PLAT-06 AC1). }
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{#WebView2Guid}', 'pv', Version) or
     RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{#WebView2Guid}', 'pv', Version) or
     RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{#WebView2Guid}', 'pv', Version))
    and (Version <> '') and (Version <> '0.0.0.0');
end;

procedure InstallWebView2();
var
  ResultCode: Integer;
begin
  WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime...';
  try
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
                          'MicrosoftEdgeWebview2Setup.exe', '', nil);
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
                SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      MsgBox('WebView2 could not be installed automatically (code ' + IntToStr(ResultCode) + ').' + #13#10 +
             'The app will open in your browser instead. You can install WebView2 later from' + #13#10 +
             'https://developer.microsoft.com/microsoft-edge/webview2/', mbInformation, MB_OK);
  except
    MsgBox('WebView2 could not be downloaded (no internet?).' + #13#10 +
           'The app will open in your browser instead until WebView2 is installed.', mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WebView2Installed() then
    InstallWebView2();
end;

{ Keep user data unless the user explicitly asks to remove it (FR-PLAT-06 AC4). }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#DataDirName}');
    if DirExists(DataDir) and not UninstallSilent() then
      if MsgBox('Also delete downloaded components (PyTorch, speech models) and your recordings?' + #13#10 +
                DataDir, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
