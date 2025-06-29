#define source_path ReadIni(SourcePath + "\setup.ini", "Data", "source_path")
#define min_windows ReadIni(SourcePath + "\setup.ini", "Data", "min_windows")

#define MyAppName "Archipelago"
#define MyAppExeName "ArchipelagoLauncher.exe"
#define MyAppIcon "data/icon.ico"
#dim VersionTuple[4]
#define MyAppVersion GetVersionComponents(source_path + '\ArchipelagoLauncher.exe', VersionTuple[0], VersionTuple[1], VersionTuple[2], VersionTuple[3])
#define MyAppVersionText Str(VersionTuple[0])+"."+Str(VersionTuple[1])+"."+Str(VersionTuple[2])


[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
AppId={{918BA46A-FAB8-460C-9DFF-AE691E1C865B}}
AppName={#MyAppName}
AppCopyright=Distributed under MIT License
AppVerName={#MyAppName} {#MyAppVersionText}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={commonappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DefaultGroupName=Archipelago
OutputDir=setups
OutputBaseFilename=Setup {#MyAppName} {#MyAppVersionText}
Compression=lzma2
SolidCompression=yes
LZMANumBlockThreads=8
ArchitecturesInstallIn64BitMode=x64 arm64
ChangesAssociations=yes
ArchitecturesAllowed=x64 arm64
AllowNoIcons=yes
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
#ifndef NO_SIGNTOOL
; You will likely have to remove the SignTool= line when testing/debugging locally or run with iscc.exe /DNO_SIGNTOOL.
; Don't include that change in PRs.
SignTool= signtool
#endif
LicenseFile= LICENSE
WizardStyle= modern
SetupLogging=yes
MinVersion={#min_windows}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}";
Name: "deletelib"; Description: "Clean existing /lib folder and subfolders including /worlds (leave checked if unsure)"; Check: ShouldShowDeleteLibTask

[Types]
Name: "full"; Description: "Full installation"
Name: "minimal"; Description: "Minimal installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core";             Description: "Archipelago"; Types: full minimal custom; Flags: fixed
[Dirs]
NAME: "{app}"; Flags: setntfscompression; Permissions: everyone-modify users-modify authusers-modify;

[Files]
Source: "{#source_path}\*"; Excludes: "*.sfc, *.log, SNI, EnemizerCLI"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#source_path}\SNI\*"; Excludes: "*.sfc, *.log"; DestDir: "{app}\SNI"; Flags: ignoreversion recursesubdirs createallsubdirs;
Source: "{#source_path}\EnemizerCLI\*"; Excludes: "*.sfc, *.log"; DestDir: "{app}\EnemizerCLI"; Flags: ignoreversion recursesubdirs createallsubdirs;
Source: "vc_redist.x64.exe"; DestDir: {tmp}; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#MyAppName} Folder"; Filename: "{app}";
Name: "{group}\{#MyAppName} Launcher"; Filename: "{app}\ArchipelagoLauncher.exe"

Name: "{commondesktop}\{#MyAppName} Folder"; Filename: "{app}"; Tasks: desktopicon
Name: "{commondesktop}\{#MyAppName} Launcher"; Filename: "{app}\ArchipelagoLauncher.exe"; Tasks: desktopicon

[Run]

Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/passive /norestart"; Check: IsVCRedist64BitNeeded; StatusMsg: "Installing VC++ redistributable..."
Filename: "{app}\ArchipelagoLauncher"; Parameters: "--update_settings"; StatusMsg: "Updating host.yaml..."; Flags: runasoriginaluser runhidden
Filename: "{app}\ArchipelagoLauncher"; Description: "{cm:LaunchProgram,{#StringChange('Launcher', '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[InstallDelete]
Type: files; Name: "{app}\*.exe"
Type: filesandordirs; Name: "{app}\SNI\lua*"
Type: filesandordirs; Name: "{app}\EnemizerCLI*"
#include "installdelete.iss"

[Registry]

Root: HKCR; Subkey: ".aplttp";                                   ValueData: "{#MyAppName}patch";        Flags: uninsdeletevalue; ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}patch";                         ValueData: "Archipelago Binary Patch"; Flags: uninsdeletekey;   ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}patch\DefaultIcon";             ValueData: "{app}\ArchipelagoSNIClient.exe,0";                  ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}patch\shell\open\command";      ValueData: """{app}\ArchipelagoSNIClient.exe"" ""%1""";         ValueType: string;  ValueName: "";

Root: HKCR; Subkey: ".archipelago";                              ValueData: "{#MyAppName}multidata";        Flags: uninsdeletevalue; ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}multidata";                     ValueData: "Archipelago Server Data";      Flags: uninsdeletekey;   ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}multidata\DefaultIcon";         ValueData: "{app}\ArchipelagoServer.exe,0";                         ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}multidata\shell\open\command";  ValueData: """{app}\ArchipelagoServer.exe"" ""%1""";                ValueType: string;  ValueName: "";

Root: HKCR; Subkey: ".apworld";                                 ValueData: "{#MyAppName}worlddata";  Flags: uninsdeletevalue; ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}worlddata";                    ValueData: "Archipelago World Data"; Flags: uninsdeletekey;   ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}worlddata\DefaultIcon";        ValueData: "{app}\ArchipelagoLauncher.exe,0";                 ValueType: string;  ValueName: "";
Root: HKCR; Subkey: "{#MyAppName}worlddata\shell\open\command"; ValueData: """{app}\ArchipelagoLauncher.exe"" ""%1""";        ValueType: string;  ValueName: "";

Root: HKCR; Subkey: "archipelago"; ValueType: "string"; ValueData: "Archipegalo Protocol"; Flags: uninsdeletekey;
Root: HKCR; Subkey: "archipelago"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: "";
Root: HKCR; Subkey: "archipelago\DefaultIcon"; ValueType: "string"; ValueData: "{app}\ArchipelagoLauncher.exe,0";
Root: HKCR; Subkey: "archipelago\shell\open\command"; ValueType: "string"; ValueData: """{app}\ArchipelagoLauncher.exe"" ""%1""";

[Code]
// See: https://stackoverflow.com/a/51614652/2287576
function IsVCRedist64BitNeeded(): boolean;
var
  strVersion: string;
begin
  if (RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', strVersion)) then
  begin
    // Is the installed version at least the packaged one ?
    Log('VC Redist x64 Version : found ' + strVersion);
    Result := (CompareStr(strVersion, 'v14.38.33130') < 0);
  end
  else
  begin
    // Not even an old version installed
    Log('VC Redist x64 is not already installed');
    Result := True;
  end;
end;

function ShouldShowDeleteLibTask: Boolean;
begin
  Result := DirExists(ExpandConstant('{app}\lib'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if WizardIsTaskSelected('deletelib') then
      DelTree(ExpandConstant('{app}\lib'), True, True, True);
  end;
end;
