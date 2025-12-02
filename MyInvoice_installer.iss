; MyInvoice_installer.iss
[Setup]
AppName=MyInvoice
AppVersion=1.0.0
AppPublisher=MyCompany
DefaultDirName={pf}\MyInvoice
DefaultGroupName=MyInvoice
UninstallDisplayIcon={app}\app.exe
Compression=lzma
SolidCompression=yes
OutputDir=installer_build
OutputBaseFilename=MyInvoice-Setup-1.0
; Optional installer icon:
; SetupIconFile=C:\Users\User\OneDrive\Desktop\invoice-app\assets\icons\invoice.ico
DisableProgramGroupPage=no
AllowNoIcons=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x86 x64
CompressionThreads=2

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Copy everything from the dist folder
Source: "C:\Users\User\OneDrive\Desktop\invoice-app\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Optional assets (only needed if assets isn’t inside dist)
Source: "C:\Users\User\OneDrive\Desktop\invoice-app\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MyInvoice"; Filename: "{app}\app.exe"
Name: "{group}\Uninstall MyInvoice"; Filename: "{uninstallexe}"

[Registry]
Root: HKLM; Subkey: "SOFTWARE\MyCompany\MyInvoice"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\app.exe"; Description: "{cm:LaunchProgram,MyInvoice}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\temp"
