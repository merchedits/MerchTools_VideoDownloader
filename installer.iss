#ifndef MyAppName
  #define MyAppName "MerchTools - Video Downloader"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.8"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "MerchEdits"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "MerchTools - Video Downloader.exe"
#endif
#ifndef MyAppSourceDir
  #define MyAppSourceDir "dist\MerchTools - Video Downloader"
#endif

[Setup]
AppId={{4A4B5B6E-DB5D-4FDF-A337-6BB269AB2DF2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
SetupIconFile=assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer-dist
OutputBaseFilename=MerchToolsVideoDownloaderSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
