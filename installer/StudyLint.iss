#ifndef MyAppVersion
  #define MyAppVersion GetEnv("STUDYLINT_VERSION")
  #if MyAppVersion == ""
    #undef MyAppVersion
    #define MyAppVersion "dev"
  #endif
#endif

#define MyAppName "StudyLint"
#define MyAppExeName "StudyLint.exe"

[Setup]
AppId={{5A926362-01F0-4A41-8CB1-39718A9BA7B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=xunguangzlj-cloud
AppPublisherURL=https://github.com/xunguangzlj-cloud/StudyLint
AppSupportURL=https://github.com/xunguangzlj-cloud/StudyLint/issues
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=StudyLint-{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\src\studylint\assets\studylint.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
