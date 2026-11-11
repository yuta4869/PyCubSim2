#define MyAppName "PyCubSim2"
#define MyAppPublisher "yuta4869"
#define MyAppURL "https://github.com/yuta4869/PyCubSim2"
#define MyAppExeName "PyCubSim2.exe"
#define MyAppUserModelId "local.yuta.pycubsim2"

#ifndef MyAppVersion
  #error MyAppVersion must be provided with /DMyAppVersion=...
#endif
#ifndef MySourceDir
  #error MySourceDir must be provided with /DMySourceDir=...
#endif
#ifndef MyOutputDir
  #error MyOutputDir must be provided with /DMyOutputDir=...
#endif
#ifndef MyIcon
  #error MyIcon must be provided with /DMyIcon=...
#endif

[Setup]
AppId={{421D3BDF-0FE2-45A1-8B2F-A63244330F3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#MyOutputDir}
OutputBaseFilename=PyCubSim2-{#MyAppVersion}-windows-x64-setup
SetupIconFile={#MyIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; AppUserModelID: "{#MyAppUserModelId}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; AppUserModelID: "{#MyAppUserModelId}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent
