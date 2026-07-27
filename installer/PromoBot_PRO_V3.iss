#define AppName "PromoBot PRO V3"
#define AppVersion "3.0.0"
#define AppPublisher "PromoBot"
#define AppExeName "PromoBot_PRO_V3.exe"

[Setup]
AppId={{8A19E776-9294-4E30-A970-A4028D94E18C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\PromoBot_PRO_V3
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=output
OutputBaseFilename=Instalar_PromoBot_PRO_V3
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
DisableProgramGroupPage=yes
LicenseFile=
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador do {#AppName}
VersionInfoCompany={#AppPublisher}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Files]
Source: "..\dist_veloz\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist_veloz\PromoBot_PRO_V3\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docker\evolution\docker-compose.yml"; DestDir: "{app}\docker\evolution"; Flags: ignoreversion
Source: "templates\app.env.template"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "templates\evolution.env.template"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "initialize_install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\scripts\promobot_supervisor.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\install_promobot_supervisor.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\installer\initialize_install.ps1"" -AppDirectory ""{app}"""; Flags: runhidden waituntilterminated; StatusMsg: "Criando configurações seguras..."
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\scripts\install_promobot_supervisor.ps1"" -PromoBotExe ""{app}\{#AppExeName}"""; Flags: runhidden waituntilterminated; StatusMsg: "Configurando inicialização em segundo plano..."; Check: ShouldInstallSupervisor
Filename: "{app}\{#AppExeName}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ""Stop-ScheduledTask -TaskName 'PromoBot_PRO_V3 Supervisor' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName 'PromoBot_PRO_V3 Supervisor' -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSupervisorTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\installer"
Type: filesandordirs; Name: "{app}\scripts"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWin64 then
  begin
    MsgBox('O PromoBot requer Windows de 64 bits.', mbError, MB_OK);
    Result := False;
  end;
end;

function ShouldInstallSupervisor(): Boolean;
begin
  Result := ExpandConstant('{param:NOSUPERVISOR|0}') <> '1';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if (not WizardSilent) and
       (not FileExists(ExpandConstant('{pf}\Docker\Docker\Docker Desktop.exe'))) then
      MsgBox(
        'O PromoBot foi instalado. Para usar o WhatsApp local, instale também o Docker Desktop e reinicie o computador. As demais funções podem ser usadas normalmente.',
        mbInformation,
        MB_OK
      );
  end;
end;
