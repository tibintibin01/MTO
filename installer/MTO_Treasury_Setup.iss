#define MyAppName "MTO Treasury System"
#define MyAppPublisher "Municipal Treasury Office"
#define MyAppExeName "Treasury.exe"
#define MyAppVersion "2.1.0"

[Setup]
AppId={{7F5E33A1-5484-49D7-9B89-4F7E092D8D3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\MTO Treasury
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=MTO_Treasury_Setup
SetupIconFile=..\assets\official\app_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{app}\logs"

[Files]
Source: "..\dist\Treasury.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\.env"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "..\server_config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "default_config.json"; DestDir: "{app}"; DestName: "config.json"; Flags: ignoreversion onlyifdoesntexist
Source: "..\MTO_Treasury_User_Manual.html"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\MTO Treasury"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\User Manual"; Filename: "{app}\MTO_Treasury_User_Manual.html"; WorkingDir: "{app}"; Flags: createonlyiffileexists
Name: "{group}\Uninstall MTO Treasury"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MTO Treasury"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,MTO Treasury}"; Flags: nowait postinstall skipifsilent
