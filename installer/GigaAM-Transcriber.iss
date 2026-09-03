; GigaAM Transcriber - Inno Setup Script
; Requires Inno Setup 6.x: https://jrsoftware.org/isinfo.php

#define AppName "GigaAM Transcriber"
#define AppVersion "1.0"
#define AppPublisher "heidurrus"
#define AppURL "https://github.com/heidurrus/gigaam-transcriber"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=GigaAM-Transcriber-Setup
Compression=lzma
SolidCompression=yes
; No admin rights needed — installs to LocalAppData
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; App files
Source: "..\app.py";            DestDir: "{app}";          Flags: ignoreversion
Source: "..\requirements.txt";  DestDir: "{app}";          Flags: ignoreversion
Source: "..\static\*";          DestDir: "{app}\static";   Flags: ignoreversion recursesubdirs createallsubdirs
; Installer helpers
Source: "setup.bat";              DestDir: "{app}";          Flags: ignoreversion
Source: "launcher.bat";           DestDir: "{app}";          Flags: ignoreversion
Source: "launcher-browser.bat";   DestDir: "{app}";          Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                Filename: "{app}\launcher.bat";         WorkingDir: "{app}"
Name: "{group}\{#AppName} (Browser Mode)"; Filename: "{app}\launcher-browser.bat"; WorkingDir: "{app}"
Name: "{group}\Run Setup (first time)";    Filename: "{app}\setup.bat";            WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}";      Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";        Filename: "{app}\launcher.bat";         WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{cmd}"; Parameters: "/c ""{app}\setup.bat"""; WorkingDir: "{app}"; Flags: waituntilterminated shellexec postinstall; StatusMsg: "Installing Python dependencies (this may take a few minutes)..."; Description: "Run first-time setup now (recommended)"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Check that Python is on PATH
  if not Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    MsgBox(
      'Python 3.10 or newer is required but was not found on PATH.' + #13#10 + #13#10 +
      'Please install Python from https://www.python.org/downloads/' + #13#10 +
      'and make sure to check "Add Python to PATH" during installation.' + #13#10 + #13#10 +
      'Then re-run this installer.',
      mbError, MB_OK
    );
    Result := False;
  end else
    Result := True;
end;
