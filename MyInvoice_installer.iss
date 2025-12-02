; MyInvoice_installer.iss
; Inno Setup script to create an installer for MyInvoice (app)
; Save next to your dist\app\ folder and run with Inno Setup Compiler (ISCC)

#define AppName "MyInvoice"
#define AppVersion "1.0.0"
#define AppPublisher "YourName"
#define AppExeName "app.exe"
#define AppId "com.yourname.myinvoice"  ; change to a reverse-domain unique id

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://example.com
AppSupportURL=https://example.com
AppUpdatesURL=https://example.com
DefaultDirName={pf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=no
OutputDir=.
OutputBaseFilename={#AppName}_Setup_{#AppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x86 x64
AllowCancelDuringInstall=yes
Uninstallable=yes
CompressionThreads=2
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Simple invoice desktop app
; use your ICO if present
#ifdef FileExists("invoice.ico")
SetupIconFile=invoice.ico
#endif

; --- Files to include ----------------
; Adjust Source: to point to your built folder content
[Files]
; Copy ALL files from dist\app\ to {app}\ (recursively)
Source: "dist\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

; Optional: if you'd rather only include the single EXE (onefile build),
; use the following instead of the line above (uncomment and adjust):
; Source: "dist\app.exe"; DestDir: "{app}"; Flags: ignoreversion

; --- Shortcuts ---
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; create desktop shortcut
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

; --- Registry entries (optional) ---
[Registry]
Root: HKCU; Subkey: "Software\{#AppPublisher}\{#AppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

; --- Uninstaller (remove installed files) ---
[UninstallDelete]
Type: filesandordirs; Name: "{app}"

; --- Run app after install option ---
[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; ---- End of script ----
